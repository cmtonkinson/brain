package main

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"

	"go.opentelemetry.io/otel/metric/noop"
	tracenoop "go.opentelemetry.io/otel/trace/noop"
)

// nopWriteCloser wraps a buffer with a no-op Close method.
type nopWriteCloser struct {
	*bytes.Buffer
}

// Close satisfies io.WriteCloser without releasing resources.
func (n nopWriteCloser) Close() error {
	return nil
}

// newTestGateway constructs a gateway with noop telemetry.
func newTestGateway(t *testing.T, cfg Config) *Gateway {
	t.Helper()
	tracer := tracenoop.NewTracerProvider().Tracer("test")
	meter := noop.NewMeterProvider().Meter("test")
	gateway, err := NewGateway(cfg, NewLogger(ioDiscard{}), tracer, meter, noopShutdown, noopShutdown)
	if err != nil {
		t.Fatalf("NewGateway failed: %v", err)
	}
	return gateway
}

// ioDiscard drops all bytes written to it.
type ioDiscard struct{}

// Write drops all bytes.
func (ioDiscard) Write(p []byte) (int, error) {
	return len(p), nil
}

// noopShutdown satisfies the gateway shutdown callbacks.
func noopShutdown(context.Context) error {
	return nil
}

// TestLoadConfigDefaults validates config parsing and defaulting behavior.
func TestLoadConfigDefaults(t *testing.T) {
	t.Parallel()

	dir := t.TempDir()
	cfgPath := filepath.Join(dir, "gateway.json")
	payload := map[string]any{
		"auth_token":      "secret",
		"allowed_clients": []string{"127.0.0.1"},
		"servers": []map[string]any{
			{
				"server_id": "unit",
				"command":   "/bin/echo",
			},
		},
	}
	data, err := json.Marshal(payload)
	if err != nil {
		t.Fatalf("marshal config: %v", err)
	}
	if err := os.WriteFile(cfgPath, data, 0o600); err != nil {
		t.Fatalf("write config: %v", err)
	}

	cfg, err := loadConfig(cfgPath)
	if err != nil {
		t.Fatalf("loadConfig failed: %v", err)
	}

	if cfg.BindHost != "127.0.0.1" {
		t.Fatalf("expected default bind host, got %q", cfg.BindHost)
	}
	if cfg.BindPort != defaultPort {
		t.Fatalf("expected default bind port %d, got %d", defaultPort, cfg.BindPort)
	}
	if cfg.Servers[0].RestartPolicy != "on-failure" {
		t.Fatalf("expected default restart policy, got %q", cfg.Servers[0].RestartPolicy)
	}
}

// TestLoadConfigRequiresAuthToken ensures config validation is enforced.
func TestLoadConfigRequiresAuthToken(t *testing.T) {
	t.Parallel()

	dir := t.TempDir()
	cfgPath := filepath.Join(dir, "gateway.json")
	payload := map[string]any{
		"allowed_clients": []string{"127.0.0.1"},
		"servers": []map[string]any{
			{
				"server_id": "unit",
				"command":   "/bin/echo",
			},
		},
	}
	data, err := json.Marshal(payload)
	if err != nil {
		t.Fatalf("marshal config: %v", err)
	}
	if err := os.WriteFile(cfgPath, data, 0o600); err != nil {
		t.Fatalf("write config: %v", err)
	}

	if _, err := loadConfig(cfgPath); err == nil {
		t.Fatal("expected auth_token validation error")
	}
}

// TestGatewayAuthChecks exercises allowlist and auth headers.
func TestGatewayAuthChecks(t *testing.T) {
	t.Parallel()

	cfg := Config{
		AuthToken:      "secret",
		AllowedClients: []string{"127.0.0.1"},
		Servers: []ServerConfig{
			{ServerID: "unit", Command: "/bin/echo"},
		},
	}
	gateway := newTestGateway(t, cfg)
	handler := gateway.routes()

	req := httptest.NewRequest(http.MethodGet, "/health", nil)
	req.RemoteAddr = "10.0.0.1:1234"
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)
	if rec.Code != http.StatusForbidden {
		t.Fatalf("expected 403, got %d", rec.Code)
	}

	req = httptest.NewRequest(http.MethodGet, "/health", nil)
	req.RemoteAddr = "127.0.0.1:1234"
	rec = httptest.NewRecorder()
	handler.ServeHTTP(rec, req)
	if rec.Code != http.StatusUnauthorized {
		t.Fatalf("expected 401, got %d", rec.Code)
	}

	req = httptest.NewRequest(http.MethodGet, "/health", nil)
	req.RemoteAddr = "127.0.0.1:1234"
	req.Header.Set("Authorization", "Bearer secret")
	rec = httptest.NewRecorder()
	handler.ServeHTTP(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", rec.Code)
	}
}

// TestGatewayRPCWrapperRoutes verifies routing through the /rpc wrapper.
func TestGatewayRPCWrapperRoutes(t *testing.T) {
	t.Parallel()

	cfg := Config{
		AuthToken:      "secret",
		AllowedClients: []string{"127.0.0.1"},
		Servers: []ServerConfig{
			{ServerID: "unit", Command: "/bin/echo"},
		},
	}
	gateway := newTestGateway(t, cfg)
	server := gateway.servers["unit"]

	responsePayload := []byte(`{"jsonrpc":"2.0","id":1,"result":{"ok":true}}`)
	server.mu.Lock()
	server.status = "ready"
	server.stdin = nopWriteCloser{Buffer: &bytes.Buffer{}}
	server.decoder = json.NewDecoder(bytes.NewReader(append(responsePayload, '\n')))
	server.mu.Unlock()

	ctx := context.Background()
	go server.worker(ctx)
	t.Cleanup(func() {
		close(server.requests)
	})

	requestBody := []byte(`{"server_id":"unit","payload":{"jsonrpc":"2.0","id":1,"method":"ping"}}`)
	req := httptest.NewRequest(http.MethodPost, "/rpc", bytes.NewReader(requestBody))
	req.RemoteAddr = "127.0.0.1:1234"
	req.Header.Set("Authorization", "Bearer secret")
	rec := httptest.NewRecorder()

	gateway.routes().ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", rec.Code)
	}

	var response GatewayResponse
	if err := json.Unmarshal(rec.Body.Bytes(), &response); err != nil {
		t.Fatalf("unmarshal response: %v", err)
	}
	if response.ServerID != "unit" {
		t.Fatalf("expected server_id unit, got %q", response.ServerID)
	}
	if !bytes.Equal(response.Payload, responsePayload) {
		t.Fatalf("unexpected payload: %s", string(response.Payload))
	}
}
