SHELL           := /bin/bash
UV              := uv
VENV 						:= .venv
VENV_PY         := $(VENV)/bin/python
PY 							:= $(if $(wildcard $(VENV_PY)),$(VENV_PY),python3)
PYTHON_VERSION  := $(shell cut -d. -f1,2 .python-version)
GLOSSARY_SRC    := docs/meta/glossary.yaml
GLOSSARY_DOC    := docs/glossary.md
GLOSSARY_GEN    := scripts/generate_glossary_docs.py
SERVICE_API_DOC := docs/service-api.md
SERVICE_API_GEN := scripts/generate_service_api_docs.py
SERVICE_API_SRC := $(shell find services -type f -path 'services/*/*/service.py' | sort)
HTTP_API_DOC    := docs/http-api.md
HTTP_API_GEN    := scripts/generate_http_api_docs.py
HTTP_API_META   := docs/meta/http-routes.yaml
HTTP_API_SRC    := $(shell (printf '%s\n' lib/core/health_api.py; find services -type f -path 'services/*/*/api.py' | sort))
OP_DOC          := docs/ops.md
OP_GEN          := scripts/generate_op_docs.py
OP_SRC          := $(shell find ops -type f | sort)
APP_COMPOSE_FILES := --file docker-compose.yaml
STACK_COMPOSE_FILES := --file docker-compose.yaml --file docker-compose.observability.yaml
APP_SERVICES     := \
	valkey \
	brain-mcp \
	postgres \
	qdrant \
	seaweedfs \
	seaweedfs-oas-bucket-init \
	brain-core \
	signal-api \
	brain-assistant
APP_PRIVATE_SERVICES := \
	brain-assistant \
	brain-core \
	brain-mcp \
	qdrant \
	signal-api
O11Y_SHARED_SERVICES := \
	postgres \
	seaweedfs \
	valkey
O11Y_SERVICES   := \
	otel-collector \
	prometheus \
	loki \
	grafana \
	langfuse-web \
	langfuse-worker \
	langfuse-postgres-init \
	clickhouse-data-init \
	clickhouse \
	seaweedfs-bucket-init
O11Y_UP_SERVICES := $(O11Y_SHARED_SERVICES) $(O11Y_SERVICES)
DIAGRAM_SRC     := img/diagrams.drawio
DIAGRAM_GEN     := img/export-diagrams.sh
DIAGRAM_PNGS    := \
	img/c4-context.png \
	img/c4-container.png \
	img/c4-component.png \
	img/boundaries-and-responsibilities.png
INTEGRATION     ?= 0
GATE_WIDTH      ?= 72

ifdef TERM
GATE_RESET      := \033[0m
GATE_INFO       := \033[1;36m
GATE_PASS       := \033[1;32m
GATE_FAIL       := \033[1;31m
GATE_WARN       := \033[1;33m
else
GATE_RESET      :=
GATE_INFO       :=
GATE_PASS       :=
GATE_FAIL       :=
GATE_WARN       :=
endif

ifneq (,$(filter integration,$(MAKECMDGOALS)))
INTEGRATION := 1
endif

ifeq ($(INTEGRATION),1)
PYTEST_INTEGRATION_ENV := BRAIN_RUN_INTEGRATION_REAL=1
endif

.PHONY: all deps deps-upgrade switch-python clean check format test test-only test-all docs docs-check up down ps app-up app-down app-down-all o11y-up o11y-down stack-up stack-down integration outline smoke smoke-only smoke-e2e smoke-docker

define run_gate
	@set +e; \
	rule=$$(printf '=%.0s' $$(seq 1 $(GATE_WIDTH))); \
	start_ns=$$($(PY) -c 'import time; print(time.perf_counter_ns())'); \
	printf "\n%b\n" "$(GATE_INFO)$${rule}$(GATE_RESET)"; \
	printf "%b\n" "$(GATE_INFO)$(1)$(GATE_RESET)"; \
	$(2); \
	status=$$?; \
	end_ns=$$($(PY) -c 'import time; print(time.perf_counter_ns())'); \
	elapsed_centis=$$(((end_ns - start_ns + 5000000) / 10000000)); \
	elapsed_major=$$((elapsed_centis / 100)); \
	elapsed_minor=$$((elapsed_centis % 100)); \
	if [ $$status -eq 0 ]; then \
		printf "%b\n\n" "$(GATE_PASS)[PASS] $(1) in $${elapsed_major}.$$(printf '%02d' $$elapsed_minor)s$(GATE_RESET)"; \
	else \
		printf "%b\n\n" "$(GATE_FAIL)[FAIL] $(1) (exit $$status)$(GATE_RESET)"; \
	fi; \
	exit $$status
endef

all: deps clean
	$(MAKE) test integration
	$(MAKE) docs

deps:
	$(UV) sync

deps-upgrade:
	if [ -n "$${PACKAGE:-}" ]; then \
		$(UV) lock --upgrade-package "$$PACKAGE"; \
	else \
		$(UV) lock --upgrade; \
	fi
	$(UV) sync

switch-python:
	@if [ -z "$${VERSION:-}" ]; then \
		echo "usage: make switch-python VERSION=3.14.2" >&2; \
		exit 1; \
	fi
	./bin/use-python "$${VERSION}"

clean:
	find . -type f -name '*.pyc' -delete
	find . -type d -name '__pycache__' -prune -exec rm -rf {} +

check:
	$(call run_gate,Ruff Check,$(PY) -m ruff check .)
	$(call run_gate,Ruff Format Check,$(PY) -m ruff format --check .)

format:
	$(PY) -m ruff format .

docs-check:
	$(call run_gate,Documentation Conventions,$(PY) scripts/check_documentation_conventions.py --check)

ifneq (,$(and $(filter test,$(MAKECMDGOALS)),$(filter docs,$(MAKECMDGOALS))))
test:
	@:
else
test: docs-check check test-only
endif

test-only:
	$(call run_gate,$(if $(filter 1,$(INTEGRATION)),Pytest (unit + integration),Pytest (unit)),$(PYTEST_INTEGRATION_ENV) $(PY) -m pytest --quiet tests resources services actors)

test-all: docs-check check
	$(MAKE) test-only integration
	$(MAKE) smoke-only
	$(MAKE) smoke-e2e
	$(MAKE) smoke-docker

integration:
	@set +e; \
	if [ "$(filter test,$(MAKECMDGOALS))" = "test" ]; then \
		:; \
	else \
		printf "\n%b\n" "$(GATE_WARN)[WARN] integration is a selector target; run 'make test integration' to include integration tests.$(GATE_RESET)"; \
	fi

smoke-e2e:
	$(call run_gate,Smoke E2E,$(PY) scripts/smoke_agent_e2e.py)

smoke-docker:
	$(call run_gate,Smoke Docker,$(PY) scripts/smoke_docker_turn.py)

smoke: docs-check check smoke-only

smoke-only:
	$(call run_gate,Pytest Smoke,$(PY) -m pytest --quiet \
		actors/assistant/tests/test_agent_turn_harness.py \
		tests/integration/test_relay_outbound_notify_api_smoke.py \
		resources/adapters/signal/tests/test_signal_adapter_wire_integration.py \
		tests/integration/test_agent_e2e_smoke.py)

ifneq (,$(and $(filter test,$(MAKECMDGOALS)),$(filter docs,$(MAKECMDGOALS))))
docs: docs-check
else
docs: $(GLOSSARY_DOC) $(SERVICE_API_DOC) $(HTTP_API_DOC) $(OP_DOC) $(DIAGRAM_PNGS)
endif

$(GLOSSARY_DOC): $(GLOSSARY_SRC) $(GLOSSARY_GEN)
	$(PY) $(GLOSSARY_GEN)

$(SERVICE_API_DOC): $(SERVICE_API_SRC) $(SERVICE_API_GEN)
	$(PY) $(SERVICE_API_GEN)

$(HTTP_API_DOC): $(HTTP_API_SRC) $(HTTP_API_GEN) $(HTTP_API_META)
	$(PY) $(HTTP_API_GEN)

$(OP_DOC): $(OP_SRC) $(OP_GEN)
	$(PY) $(OP_GEN)

$(DIAGRAM_PNGS) &: $(DIAGRAM_SRC) $(DIAGRAM_GEN)
	$(DIAGRAM_GEN) $(DIAGRAM_SRC)

#############################################################################
# development conveniences
#############################################################################
up: app-up

down: stack-down

ps:
	docker compose $(STACK_COMPOSE_FILES) ps

app-up:
	PYTHON_VERSION=$(PYTHON_VERSION) docker compose $(APP_COMPOSE_FILES) up --build --detach

app-down:
	docker compose $(STACK_COMPOSE_FILES) rm --force --stop $(APP_PRIVATE_SERVICES)

app-down-all:
	docker compose $(APP_COMPOSE_FILES) rm --force --stop $(APP_SERVICES)

o11y-up:
	PYTHON_VERSION=$(PYTHON_VERSION) docker compose $(STACK_COMPOSE_FILES) up --build --detach $(O11Y_UP_SERVICES)

o11y-down:
	docker compose $(STACK_COMPOSE_FILES) rm --force --stop $(O11Y_SERVICES)

stack-up:
	PYTHON_VERSION=$(PYTHON_VERSION) docker compose $(STACK_COMPOSE_FILES) up --build --detach

stack-down:
	docker compose $(STACK_COMPOSE_FILES) down

outline:
	@tree -d -I __pycache__ -I tests -I data -I migrations actors lib resources services
