package main

import (
	"bufio"
	"context"
	"crypto/rand"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/exporters/otlp/otlpmetric/otlpmetricgrpc"
	"go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracegrpc"
	"go.opentelemetry.io/otel/metric"
	sdkmetric "go.opentelemetry.io/otel/sdk/metric"
	"go.opentelemetry.io/otel/sdk/resource"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	semconv "go.opentelemetry.io/otel/semconv/v1.24.0"
	"go.opentelemetry.io/otel/trace"
)

const (
	serviceName             = "host-mcp-gateway"
	serviceVersion          = "0.1.0"
	defaultPort             = 7411
	defaultRequestTimeoutMS = 30000
	defaultRestartBackoffMS = 2000
)

type Config struct {
	BindHost         string         `json:"bind_host"`
	BindPort         int            `json:"bind_port"`
	AuthToken        string         `json:"auth_token"`
	AllowedClients   []string       `json:"allowed_clients"`
	RequestTimeoutMS int            `json:"request_timeout_ms"`
	RestartBackoffMS int            `json:"restart_backoff_ms"`
	Servers          []ServerConfig `json:"servers"`
}

type ServerConfig struct {
	ServerID         string            `json:"server_id"`
	Command          string            `json:"command"`
	Args             []string          `json:"args"`
	WorkingDir       string            `json:"working_dir"`
	Env              map[string]string `json:"env"`
	Autostart        bool              `json:"autostart"`
	RestartPolicy    string            `json:"restart_policy"`
	StartupTimeoutMS int               `json:"startup_timeout_ms"`
}

type Gateway struct {
	cfg           Config
	logger        *Logger
	servers       map[string]*ManagedServer
	allowedIPs    []net.IP
	allowedCIDRs  []*net.IPNet
	startTime     time.Time
	tracer        trace.Tracer
	meter         metric.Meter
	metrics       *GatewayMetrics
	shutdownTrace func(context.Context) error
	shutdownMet   func(context.Context) error
}

type GatewayMetrics struct {
	requests     metric.Int64Counter
	latency      metric.Int64Histogram
	restarts     metric.Int64Counter
	authFailures metric.Int64Counter
}

type GatewayRequest struct {
	ServerID string          `json:"server_id"`
	Payload  json.RawMessage `json:"payload"`
}

type GatewayResponse struct {
	ServerID string          `json:"server_id"`
	Payload  json.RawMessage `json:"payload,omitempty"`
	Error    *GatewayError   `json:"error,omitempty"`
}

type GatewayError struct {
	ErrorCode string `json:"error_code"`
	Message   string `json:"message"`
	ServerID  string `json:"server_id,omitempty"`
	RequestID string `json:"request_id,omitempty"`
}

type Logger struct {
	mu     sync.Mutex
	writer io.Writer
}

func NewLogger(writer io.Writer) *Logger {
	return &Logger{writer: writer}
}

func (l *Logger) Log(ctx context.Context, level, message string, fields map[string]any) {
	entry := map[string]any{
		"timestamp": time.Now().UTC().Format(time.RFC3339Nano),
		"service":   serviceName,
		"level":     strings.ToUpper(level),
		"message":   message,
		"event":     message,
	}

	if span := trace.SpanFromContext(ctx); span != nil {
		spanCtx := span.SpanContext()
		if spanCtx.IsValid() {
			entry["trace_id"] = spanCtx.TraceID().String()
			entry["span_id"] = spanCtx.SpanID().String()
		}
	}

	for key, value := range fields {
		entry[key] = value
	}

	payload, err := json.Marshal(entry)
	if err != nil {
		return
	}

	l.mu.Lock()
	defer l.mu.Unlock()
	_, _ = l.writer.Write(payload)
	_, _ = l.writer.Write([]byte("\n"))
}

type ManagedServer struct {
	cfg            ServerConfig
	logger         *Logger
	mu             sync.Mutex
	status         string
	cmd            *exec.Cmd
	stdin          io.WriteCloser
	stdout         *bufio.Reader
	decoder        *json.Decoder
	stderr         io.ReadCloser
	sessionID      string
	requests       chan serverRequest
	workerOnce     sync.Once
	metrics        *GatewayMetrics
	requestTimeout time.Duration
	restartBackoff time.Duration
	restartCount   int
	lastExitCode   int
	lastExitAt     time.Time
}

type serverRequest struct {
	ctx       context.Context
	payload   []byte
	requestID string
	response  chan serverResponse
}

type serverResponse struct {
	payload []byte
	err     error
}

func main() {
	configPath := flag.String("config", "~/.config/brain/host-mcp-gateway.json", "Path to gateway config")
	flag.Parse()

	cfg, err := loadConfig(*configPath)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Failed to load config: %v\n", err)
		os.Exit(1)
	}

	logger := NewLogger(os.Stdout)
	ctx := context.Background()
	tracer, meter, shutdownTrace, shutdownMet, err := setupObservability(ctx)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Failed to setup observability: %v\n", err)
		os.Exit(1)
	}
	defer func() {
		_ = shutdownTrace(context.Background())
		_ = shutdownMet(context.Background())
	}()

	gateway, err := NewGateway(*cfg, logger, tracer, meter, shutdownTrace, shutdownMet)
	if err != nil {
		logger.Log(ctx, "error", "gateway_init_failed", map[string]any{"error": err.Error()})
		os.Exit(1)
	}

	gateway.logger.Log(ctx, "info", "gateway_starting", map[string]any{"bind_host": gateway.cfg.BindHost, "bind_port": gateway.cfg.BindPort})
	gateway.startAutostartServers(ctx)

	addr := fmt.Sprintf("%s:%d", gateway.cfg.BindHost, gateway.cfg.BindPort)
	server := &http.Server{
		Addr:    addr,
		Handler: gateway.routes(),
	}

	if err := server.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
		gateway.logger.Log(ctx, "error", "gateway_listen_failed", map[string]any{"error": err.Error()})
		os.Exit(1)
	}
}

func setupObservability(ctx context.Context) (trace.Tracer, metric.Meter, func(context.Context) error, func(context.Context) error, error) {
	endpoint := strings.TrimSpace(os.Getenv("OTEL_EXPORTER_OTLP_ENDPOINT"))
	if endpoint == "" {
		return nil, nil, nil, nil, errors.New("OTEL_EXPORTER_OTLP_ENDPOINT is required")
	}

	res, err := resource.New(ctx,
		resource.WithAttributes(
			semconv.ServiceName(serviceName),
			semconv.ServiceVersion(serviceVersion),
		),
	)
	if err != nil {
		return nil, nil, nil, nil, err
	}

	traceExporter, err := otlptracegrpc.New(ctx, otlptracegrpc.WithEndpoint(endpoint), otlptracegrpc.WithInsecure())
	if err != nil {
		return nil, nil, nil, nil, err
	}
	traceProvider := sdktrace.NewTracerProvider(
		sdktrace.WithResource(res),
		sdktrace.WithBatcher(traceExporter),
	)
	otel.SetTracerProvider(traceProvider)

	metricExporter, err := otlpmetricgrpc.New(ctx, otlpmetricgrpc.WithEndpoint(endpoint), otlpmetricgrpc.WithInsecure())
	if err != nil {
		return nil, nil, nil, nil, err
	}
	metricReader := sdkmetric.NewPeriodicReader(metricExporter)
	metricProvider := sdkmetric.NewMeterProvider(
		sdkmetric.WithResource(res),
		sdkmetric.WithReader(metricReader),
	)
	otel.SetMeterProvider(metricProvider)

	tracer := otel.Tracer(serviceName)
	meter := otel.Meter(serviceName)

	return tracer, meter, traceProvider.Shutdown, metricProvider.Shutdown, nil
}

func NewGateway(cfg Config, logger *Logger, tracer trace.Tracer, meter metric.Meter, shutdownTrace func(context.Context) error, shutdownMet func(context.Context) error) (*Gateway, error) {
	cfg = applyConfigDefaults(cfg)
	if cfg.RequestTimeoutMS < 0 {
		return nil, errors.New("request_timeout_ms must be >= 0")
	}
	if cfg.RestartBackoffMS < 0 {
		return nil, errors.New("restart_backoff_ms must be >= 0")
	}

	allowedIPs, allowedCIDRs, err := parseAllowlist(cfg.AllowedClients)
	if err != nil {
		return nil, err
	}

	servers := make(map[string]*ManagedServer)
	for _, server := range cfg.Servers {
		if _, exists := servers[server.ServerID]; exists {
			return nil, fmt.Errorf("duplicate server_id: %s", server.ServerID)
		}
		servers[server.ServerID] = &ManagedServer{
			cfg:            server,
			logger:         logger,
			status:         "stopped",
			requests:       make(chan serverRequest),
			metrics:        nil,
			requestTimeout: time.Duration(cfg.RequestTimeoutMS) * time.Millisecond,
			restartBackoff: time.Duration(cfg.RestartBackoffMS) * time.Millisecond,
		}
	}

	metrics, err := initMetrics(meter)
	if err != nil {
		return nil, err
	}

	gateway := &Gateway{
		cfg:           cfg,
		logger:        logger,
		servers:       servers,
		allowedIPs:    allowedIPs,
		allowedCIDRs:  allowedCIDRs,
		startTime:     time.Now(),
		tracer:        tracer,
		meter:         meter,
		metrics:       metrics,
		shutdownTrace: shutdownTrace,
		shutdownMet:   shutdownMet,
	}

	for _, server := range gateway.servers {
		server.metrics = metrics
	}

	return gateway, nil
}

func initMetrics(meter metric.Meter) (*GatewayMetrics, error) {
	requests, err := meter.Int64Counter(
		"brain.mcp.gateway.requests",
		metric.WithDescription("Total gateway MCP requests"),
	)
	if err != nil {
		return nil, err
	}
	latency, err := meter.Int64Histogram(
		"brain.mcp.gateway.latency",
		metric.WithDescription("Gateway MCP latency"),
		metric.WithUnit("ms"),
	)
	if err != nil {
		return nil, err
	}
	restarts, err := meter.Int64Counter(
		"brain.mcp.gateway.restarts",
		metric.WithDescription("Gateway MCP server restarts"),
	)
	if err != nil {
		return nil, err
	}
	authFailures, err := meter.Int64Counter(
		"brain.mcp.gateway.auth_failures",
		metric.WithDescription("Gateway authentication failures"),
	)
	if err != nil {
		return nil, err
	}

	return &GatewayMetrics{
		requests:     requests,
		latency:      latency,
		restarts:     restarts,
		authFailures: authFailures,
	}, nil
}

func (g *Gateway) routes() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("/health", g.handleHealth)
	mux.HandleFunc("/servers", g.handleServers)
	mux.HandleFunc("/rpc", g.handleRPCWrapper)
	mux.HandleFunc("/", g.handleRPCDirect)
	return g.withMiddleware(mux)
}

func (g *Gateway) withMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		ctx := r.Context()
		if !g.isAllowedClient(r) {
			g.metrics.authFailures.Add(ctx, 1)
			g.logger.Log(ctx, "warn", "gateway_auth_denied", map[string]any{"remote": r.RemoteAddr})
			writeError(w, http.StatusForbidden, GatewayError{ErrorCode: "auth_denied", Message: "client not allowed"})
			return
		}

		if !g.checkAuth(r) {
			g.metrics.authFailures.Add(ctx, 1)
			g.logger.Log(ctx, "warn", "gateway_auth_failed", map[string]any{"remote": r.RemoteAddr})
			writeError(w, http.StatusUnauthorized, GatewayError{ErrorCode: "auth_failed", Message: "invalid auth token"})
			return
		}

		next.ServeHTTP(w, r)
	})
}

func (g *Gateway) checkAuth(r *http.Request) bool {
	token := r.Header.Get("Authorization")
	const prefix = "Bearer "
	if !strings.HasPrefix(token, prefix) {
		return false
	}
	return strings.TrimSpace(strings.TrimPrefix(token, prefix)) == g.cfg.AuthToken
}

func (g *Gateway) isAllowedClient(r *http.Request) bool {
	host, _, err := net.SplitHostPort(r.RemoteAddr)
	if err != nil {
		host = r.RemoteAddr
	}
	ip := net.ParseIP(host)
	if ip == nil {
		return false
	}
	for _, allowedIP := range g.allowedIPs {
		if allowedIP.Equal(ip) {
			return true
		}
	}
	for _, cidr := range g.allowedCIDRs {
		if cidr.Contains(ip) {
			return true
		}
	}
	return false
}

func (g *Gateway) handleHealth(w http.ResponseWriter, r *http.Request) {
	ctx := r.Context()
	status := "ok"
	serverStatuses := g.collectServerStatuses()
	for _, s := range serverStatuses {
		statusValue, _ := s["status"].(string)
		if statusValue != "ready" {
			status = "degraded"
			break
		}
	}

	response := map[string]any{
		"status":         status,
		"version":        serviceVersion,
		"uptime_seconds": int(time.Since(g.startTime).Seconds()),
		"servers":        serverStatuses,
	}

	g.writeJSON(ctx, w, http.StatusOK, response)
}

func (g *Gateway) handleServers(w http.ResponseWriter, r *http.Request) {
	ctx := r.Context()
	g.writeJSON(ctx, w, http.StatusOK, map[string]any{
		"servers": g.collectServerStatuses(),
	})
}

func (g *Gateway) handleRPCWrapper(w http.ResponseWriter, r *http.Request) {
	ctx := r.Context()
	start := time.Now()

	var req GatewayRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		g.metrics.requests.Add(ctx, 1, metric.WithAttributes(attribute.String("status", "invalid")))
		writeError(w, http.StatusBadRequest, GatewayError{ErrorCode: "invalid_request", Message: "invalid json"})
		return
	}

	requestID := extractRequestID(req.Payload)
	spanCtx, span := g.tracer.Start(ctx, "mcp_gateway.request",
		trace.WithAttributes(
			attribute.String("server_id", req.ServerID),
			attribute.String("request_id", requestID),
		),
	)
	defer span.End()

	server, ok := g.servers[req.ServerID]
	if !ok {
		g.metrics.requests.Add(spanCtx, 1, metric.WithAttributes(attribute.String("status", "not_found")))
		g.logger.Log(spanCtx, "warn", "gateway_server_not_found", map[string]any{"server_id": req.ServerID})
		writeError(w, http.StatusNotFound, GatewayError{ErrorCode: "server_not_found", Message: "unknown server_id", ServerID: req.ServerID, RequestID: requestID})
		return
	}

	if isNotification(req.Payload) {
		if err := server.Send(spanCtx, req.Payload); err != nil {
			g.metrics.requests.Add(spanCtx, 1, metric.WithAttributes(attribute.String("server_id", req.ServerID), attribute.String("status", "error")))
			g.logger.Log(spanCtx, "error", "gateway_request_failed", map[string]any{"server_id": req.ServerID, "error": err.Error(), "request_id": requestID})
			writeError(w, http.StatusBadGateway, GatewayError{ErrorCode: "server_error", Message: err.Error(), ServerID: req.ServerID, RequestID: requestID})
			return
		}
		g.metrics.requests.Add(spanCtx, 1, metric.WithAttributes(attribute.String("server_id", req.ServerID), attribute.String("status", "accepted")))
		w.WriteHeader(http.StatusAccepted)
		return
	}

	responsePayload, err := server.Call(spanCtx, req.Payload, requestID)
	statusLabel := "success"
	if err != nil {
		statusLabel = "error"
	}
	g.metrics.requests.Add(spanCtx, 1, metric.WithAttributes(attribute.String("server_id", req.ServerID), attribute.String("status", statusLabel)))
	g.metrics.latency.Record(spanCtx, time.Since(start).Milliseconds(), metric.WithAttributes(attribute.String("server_id", req.ServerID)))

	if err != nil {
		g.logger.Log(spanCtx, "error", "gateway_request_failed", map[string]any{"server_id": req.ServerID, "error": err.Error(), "request_id": requestID})
		writeError(w, http.StatusBadGateway, GatewayError{ErrorCode: "server_error", Message: err.Error(), ServerID: req.ServerID, RequestID: requestID})
		return
	}

	g.logger.Log(spanCtx, "info", "gateway_request_ok", map[string]any{"server_id": req.ServerID, "request_id": requestID})
	g.writeJSON(spanCtx, w, http.StatusOK, GatewayResponse{ServerID: req.ServerID, Payload: responsePayload})
}

func (g *Gateway) handleRPCDirect(w http.ResponseWriter, r *http.Request) {
	if !strings.HasSuffix(r.URL.Path, "/rpc") {
		writeError(w, http.StatusNotFound, GatewayError{ErrorCode: "not_found", Message: "unknown endpoint"})
		return
	}

	serverID := strings.TrimSuffix(strings.TrimPrefix(r.URL.Path, "/"), "/rpc")
	if serverID == "" {
		writeError(w, http.StatusNotFound, GatewayError{ErrorCode: "server_not_found", Message: "missing server_id"})
		return
	}

	ctx := r.Context()
	start := time.Now()

	if r.Method == http.MethodGet {
		g.handleRPCStream(ctx, w, r, serverID)
		return
	}

	body, err := io.ReadAll(r.Body)
	if err != nil {
		g.metrics.requests.Add(ctx, 1, metric.WithAttributes(attribute.String("status", "invalid")))
		writeError(w, http.StatusBadRequest, GatewayError{ErrorCode: "invalid_request", Message: "invalid body"})
		return
	}

	requestID := extractRequestID(body)
	spanCtx, span := g.tracer.Start(ctx, "mcp_gateway.request",
		trace.WithAttributes(
			attribute.String("server_id", serverID),
			attribute.String("request_id", requestID),
		),
	)
	defer span.End()

	server, ok := g.servers[serverID]
	if !ok {
		g.metrics.requests.Add(spanCtx, 1, metric.WithAttributes(attribute.String("status", "not_found")))
		g.logger.Log(spanCtx, "warn", "gateway_server_not_found", map[string]any{"server_id": serverID})
		writeError(w, http.StatusNotFound, GatewayError{ErrorCode: "server_not_found", Message: "unknown server_id", ServerID: serverID, RequestID: requestID})
		return
	}

	if isNotification(body) {
		if err := server.Send(spanCtx, body); err != nil {
			g.metrics.requests.Add(spanCtx, 1, metric.WithAttributes(attribute.String("server_id", serverID), attribute.String("status", "error")))
			g.logger.Log(spanCtx, "error", "gateway_request_failed", map[string]any{"server_id": serverID, "error": err.Error(), "request_id": requestID})
			writeError(w, http.StatusBadGateway, GatewayError{ErrorCode: "server_error", Message: err.Error(), ServerID: serverID, RequestID: requestID})
			return
		}
		g.metrics.requests.Add(spanCtx, 1, metric.WithAttributes(attribute.String("server_id", serverID), attribute.String("status", "accepted")))
		w.WriteHeader(http.StatusAccepted)
		return
	}

	responsePayload, err := server.Call(spanCtx, body, requestID)
	statusLabel := "success"
	if err != nil {
		statusLabel = "error"
	}
	g.metrics.requests.Add(spanCtx, 1, metric.WithAttributes(attribute.String("server_id", serverID), attribute.String("status", statusLabel)))
	g.metrics.latency.Record(spanCtx, time.Since(start).Milliseconds(), metric.WithAttributes(attribute.String("server_id", serverID)))

	if err != nil {
		g.logger.Log(spanCtx, "error", "gateway_request_failed", map[string]any{"server_id": serverID, "error": err.Error(), "request_id": requestID})
		writeError(w, http.StatusBadGateway, GatewayError{ErrorCode: "server_error", Message: err.Error(), ServerID: serverID, RequestID: requestID})
		return
	}

	g.logger.Log(spanCtx, "info", "gateway_request_ok", map[string]any{"server_id": serverID, "request_id": requestID})
	g.writeRawJSON(spanCtx, w, http.StatusOK, responsePayload, server)
}

func (g *Gateway) handleRPCStream(ctx context.Context, w http.ResponseWriter, r *http.Request, serverID string) {
	server, ok := g.servers[serverID]
	if !ok {
		writeError(w, http.StatusNotFound, GatewayError{ErrorCode: "server_not_found", Message: "unknown server_id", ServerID: serverID})
		return
	}

	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("Connection", "keep-alive")
	if sessionID := server.ensureSessionID(); sessionID != "" {
		w.Header().Set("MCP-Session-Id", sessionID)
	}

	flusher, ok := w.(http.Flusher)
	if !ok {
		writeError(w, http.StatusInternalServerError, GatewayError{ErrorCode: "streaming_not_supported", Message: "response does not support streaming"})
		return
	}

	// Initial comment to establish stream
	_, _ = w.Write([]byte(": ok\n\n"))
	flusher.Flush()

	ticker := time.NewTicker(25 * time.Second)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			_, _ = w.Write([]byte(": keep-alive\n\n"))
			flusher.Flush()
		}
	}
}

func (g *Gateway) writeJSON(ctx context.Context, w http.ResponseWriter, status int, payload any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	if err := json.NewEncoder(w).Encode(payload); err != nil {
		g.logger.Log(ctx, "error", "gateway_write_failed", map[string]any{"error": err.Error()})
	}
}

func (g *Gateway) writeRawJSON(ctx context.Context, w http.ResponseWriter, status int, payload json.RawMessage, server *ManagedServer) {
	w.Header().Set("Content-Type", "application/json")
	if server != nil && isInitializeRequest(payload) {
		sessionID := server.ensureSessionID()
		if sessionID != "" {
			w.Header().Set("MCP-Session-Id", sessionID)
		}
	}
	w.WriteHeader(status)
	if _, err := w.Write(payload); err != nil {
		g.logger.Log(ctx, "error", "gateway_write_failed", map[string]any{"error": err.Error()})
	}
}

func (g *Gateway) collectServerStatuses() []map[string]any {
	statuses := make([]map[string]any, 0, len(g.servers))
	for _, server := range g.servers {
		statuses = append(statuses, server.Status())
	}
	return statuses
}

func (g *Gateway) startAutostartServers(ctx context.Context) {
	for _, server := range g.servers {
		if !server.cfg.Autostart {
			continue
		}
		if err := server.Start(ctx); err != nil {
			g.logger.Log(ctx, "error", "gateway_server_start_failed", map[string]any{"server_id": server.cfg.ServerID, "error": err.Error()})
		}
	}
}

func (s *ManagedServer) Start(ctx context.Context) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	if s.status == "ready" || s.status == "starting" {
		return nil
	}

	cmd := exec.Command(s.cfg.Command, s.cfg.Args...)
	if s.cfg.WorkingDir != "" {
		cmd.Dir = s.cfg.WorkingDir
	}
	cmd.Env = os.Environ()
	for key, value := range s.cfg.Env {
		cmd.Env = append(cmd.Env, fmt.Sprintf("%s=%s", key, value))
	}

	stdin, err := cmd.StdinPipe()
	if err != nil {
		return err
	}
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		return err
	}
	stderr, err := cmd.StderrPipe()
	if err != nil {
		return err
	}

	s.status = "starting"
	s.cmd = cmd
	s.stdin = stdin
	s.stdout = bufio.NewReader(stdout)
	s.decoder = json.NewDecoder(s.stdout)
	s.stderr = stderr

	if err := cmd.Start(); err != nil {
		s.status = "error"
		return err
	}

	s.status = "ready"
	go s.readStderr(ctx)
	go s.waitForExit(ctx)
	s.workerOnce.Do(func() {
		go s.worker(ctx)
	})

	s.logger.Log(ctx, "info", "mcp_server_started", map[string]any{"server_id": s.cfg.ServerID, "pid": cmd.Process.Pid})

	return nil
}

func (s *ManagedServer) Status() map[string]any {
	s.mu.Lock()
	defer s.mu.Unlock()

	pid := 0
	if s.cmd != nil && s.cmd.Process != nil {
		pid = s.cmd.Process.Pid
	}

	return map[string]any{
		"server_id":         s.cfg.ServerID,
		"status":            s.status,
		"pid":               pid,
		"restart_count":     s.restartCount,
		"last_exit_code":    s.lastExitCode,
		"last_exit_at":      formatTime(s.lastExitAt),
		"session_id":        s.sessionID,
		"autostart":         s.cfg.Autostart,
		"restart_policy":    s.cfg.RestartPolicy,
		"command":           s.cfg.Command,
		"working_directory": s.cfg.WorkingDir,
	}
}

func (s *ManagedServer) Call(ctx context.Context, payload []byte, requestID string) (json.RawMessage, error) {
	if err := s.ensureRunning(ctx); err != nil {
		return nil, err
	}

	respCh := make(chan serverResponse, 1)
	request := serverRequest{ctx: ctx, payload: payload, requestID: requestID, response: respCh}

	select {
	case s.requests <- request:
	case <-ctx.Done():
		return nil, ctx.Err()
	}

	select {
	case resp := <-respCh:
		return resp.payload, resp.err
	case <-ctx.Done():
		return nil, ctx.Err()
	}
}

func (s *ManagedServer) Send(ctx context.Context, payload []byte) error {
	if err := s.ensureRunning(ctx); err != nil {
		return err
	}

	s.mu.Lock()
	stdin := s.stdin
	s.mu.Unlock()

	if stdin == nil {
		return fmt.Errorf("server %s is not ready", s.cfg.ServerID)
	}

	line := append([]byte{}, payload...)
	if len(line) == 0 {
		return errors.New("empty payload")
	}
	if line[len(line)-1] != '\n' {
		line = append(line, '\n')
	}

	return writeAll(stdin, line)
}

func (s *ManagedServer) ensureRunning(ctx context.Context) error {
	s.mu.Lock()
	status := s.status
	s.mu.Unlock()

	if status == "ready" {
		return nil
	}

	if !s.cfg.Autostart {
		return fmt.Errorf("server %s is not running", s.cfg.ServerID)
	}

	return s.Start(ctx)
}

func (s *ManagedServer) ensureSessionID() string {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.sessionID == "" {
		s.sessionID = randomSessionID()
	}
	return s.sessionID
}

func (s *ManagedServer) worker(ctx context.Context) {
	for req := range s.requests {
		callCtx, cancel := context.WithTimeout(req.ctx, s.requestTimeout)
		payload, err := s.sendAndReceive(callCtx, req.payload, req.requestID)
		cancel()

		req.response <- serverResponse{payload: payload, err: err}
	}
}

func (s *ManagedServer) sendAndReceive(ctx context.Context, payload []byte, requestID string) (json.RawMessage, error) {
	s.mu.Lock()
	stdin := s.stdin
	decoder := s.decoder
	s.mu.Unlock()

	if stdin == nil || decoder == nil {
		return nil, fmt.Errorf("server %s is not ready", s.cfg.ServerID)
	}

	line := append([]byte{}, payload...)
	if len(line) == 0 {
		return nil, errors.New("empty payload")
	}
	if line[len(line)-1] != '\n' {
		line = append(line, '\n')
	}

	if err := writeAll(stdin, line); err != nil {
		return nil, err
	}
	respCh := make(chan serverResponse, 1)
	go func() {
		var raw json.RawMessage
		err := decoder.Decode(&raw)
		respCh <- serverResponse{payload: raw, err: err}
	}()

	select {
	case resp := <-respCh:
		return resp.payload, resp.err
	case <-ctx.Done():
		return nil, ctx.Err()
	}
}

func (s *ManagedServer) readStderr(ctx context.Context) {
	s.mu.Lock()
	stderr := s.stderr
	s.mu.Unlock()
	if stderr == nil {
		return
	}

	scanner := bufio.NewScanner(stderr)
	for scanner.Scan() {
		line := scanner.Text()
		s.logger.Log(ctx, "warn", "mcp_server_stderr", map[string]any{"server_id": s.cfg.ServerID, "line": line})
	}
}

func (s *ManagedServer) waitForExit(ctx context.Context) {
	s.mu.Lock()
	cmd := s.cmd
	s.mu.Unlock()
	if cmd == nil {
		return
	}

	err := cmd.Wait()
	code := 0
	if err != nil {
		if exitErr, ok := err.(*exec.ExitError); ok {
			code = exitErr.ExitCode()
		} else {
			code = -1
		}
	}

	s.mu.Lock()
	s.status = "stopped"
	s.lastExitCode = code
	s.lastExitAt = time.Now()
	s.cmd = nil
	s.stdin = nil
	s.stdout = nil
	s.decoder = nil
	s.stderr = nil
	s.mu.Unlock()

	s.logger.Log(ctx, "warn", "mcp_server_exited", map[string]any{"server_id": s.cfg.ServerID, "exit_code": code})

	shouldRestart := s.cfg.RestartPolicy == "always" || (s.cfg.RestartPolicy == "on-failure" && code != 0)
	if shouldRestart {
		s.mu.Lock()
		s.restartCount++
		s.mu.Unlock()
		if s.metrics != nil {
			s.metrics.restarts.Add(ctx, 1, metric.WithAttributes(attribute.String("server_id", s.cfg.ServerID)))
		}
		time.Sleep(s.restartBackoff)
		_ = s.Start(ctx)
	}
}

func loadConfig(path string) (*Config, error) {
	expanded, err := expandPath(path)
	if err != nil {
		return nil, err
	}
	data, err := os.ReadFile(expanded)
	if err != nil {
		return nil, err
	}

	var cfg Config
	if err := json.Unmarshal(data, &cfg); err != nil {
		return nil, err
	}

	cfg = applyConfigDefaults(cfg)

	if cfg.RequestTimeoutMS < 0 {
		return nil, errors.New("request_timeout_ms must be >= 0")
	}
	if cfg.RestartBackoffMS < 0 {
		return nil, errors.New("restart_backoff_ms must be >= 0")
	}
	if cfg.AuthToken == "" {
		return nil, errors.New("auth_token is required")
	}
	if len(cfg.AllowedClients) == 0 {
		return nil, errors.New("allowed_clients is required")
	}
	if len(cfg.Servers) == 0 {
		return nil, errors.New("servers is required")
	}

	for _, server := range cfg.Servers {
		if server.ServerID == "" {
			return nil, errors.New("server_id is required")
		}
		if server.Command == "" {
			return nil, fmt.Errorf("command is required for server_id %s", server.ServerID)
		}
	}

	for idx, server := range cfg.Servers {
		if server.RestartPolicy == "" {
			cfg.Servers[idx].RestartPolicy = "on-failure"
		}
	}

	return &cfg, nil
}

func applyConfigDefaults(cfg Config) Config {
	if cfg.BindHost == "" {
		cfg.BindHost = "127.0.0.1"
	}
	if cfg.BindPort == 0 {
		cfg.BindPort = defaultPort
	}
	if cfg.RequestTimeoutMS == 0 {
		cfg.RequestTimeoutMS = defaultRequestTimeoutMS
	}
	if cfg.RestartBackoffMS == 0 {
		cfg.RestartBackoffMS = defaultRestartBackoffMS
	}
	return cfg
}

func expandPath(path string) (string, error) {
	if strings.HasPrefix(path, "~") {
		home, err := os.UserHomeDir()
		if err != nil {
			return "", err
		}
		return filepath.Join(home, strings.TrimPrefix(path, "~/")), nil
	}
	return path, nil
}

func parseAllowlist(entries []string) ([]net.IP, []*net.IPNet, error) {
	var ips []net.IP
	var cidrs []*net.IPNet

	for _, entry := range entries {
		trimmed := strings.TrimSpace(entry)
		if trimmed == "" {
			continue
		}

		if strings.EqualFold(trimmed, "localhost") {
			ips = append(ips, net.ParseIP("127.0.0.1"), net.ParseIP("::1"))
			continue
		}

		if strings.Contains(trimmed, "/") {
			_, ipnet, err := net.ParseCIDR(trimmed)
			if err != nil {
				return nil, nil, fmt.Errorf("invalid CIDR: %s", trimmed)
			}
			cidrs = append(cidrs, ipnet)
			continue
		}

		ip := net.ParseIP(trimmed)
		if ip == nil {
			return nil, nil, fmt.Errorf("invalid IP: %s", trimmed)
		}
		ips = append(ips, ip)
	}

	return ips, cidrs, nil
}

func extractRequestID(payload json.RawMessage) string {
	var data map[string]any
	if err := json.Unmarshal(payload, &data); err != nil {
		return ""
	}
	if id, ok := data["id"]; ok {
		return fmt.Sprintf("%v", id)
	}
	return ""
}

func writeError(w http.ResponseWriter, status int, gatewayErr GatewayError) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(GatewayResponse{Error: &gatewayErr})
}

func writeAll(writer io.Writer, data []byte) error {
	for len(data) > 0 {
		written, err := writer.Write(data)
		if err != nil {
			return err
		}
		data = data[written:]
	}
	return nil
}

func formatTime(value time.Time) string {
	if value.IsZero() {
		return ""
	}
	return value.UTC().Format(time.RFC3339Nano)
}

func isNotification(payload []byte) bool {
	method, hasID := parseMethodAndID(payload)
	return method != "" && !hasID
}

func isInitializeRequest(payload []byte) bool {
	method, _ := parseMethodAndID(payload)
	return method == "initialize"
}

func parseMethodAndID(payload []byte) (string, bool) {
	var data map[string]any
	if err := json.Unmarshal(payload, &data); err != nil {
		return "", false
	}
	method, _ := data["method"].(string)
	_, hasID := data["id"]
	return method, hasID
}

func randomSessionID() string {
	var bytes [16]byte
	if _, err := rand.Read(bytes[:]); err != nil {
		return ""
	}
	return fmt.Sprintf("%x", bytes[:])
}
