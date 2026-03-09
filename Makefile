SHELL           := /bin/bash
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
HTTP_API_SRC    := $(shell (printf '%s\n' packages/brain_core/health_api.py; find services -type f -path 'services/*/*/api.py' | sort))
CAPABILITY_DOC  := docs/capabilities.md
CAPABILITY_GEN  := scripts/generate_capability_docs.py
CAPABILITY_SRC  := $(shell find capabilities -type f | sort)
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

.PHONY: all deps deps-upgrade clean check format test test-all docs up down integration outline smoke smoke-e2e smoke-docker

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
	$(PY) -m pip install --upgrade pip pip-tools
	$(PY) -m piptools sync requirements.txt

deps-upgrade:
	if [ -n "$${PACKAGE:-}" ]; then \
		$(PY) -m piptools compile --upgrade-package "$$PACKAGE" --output-file requirements.txt requirements.in; \
	else \
		$(PY) -m piptools compile --upgrade --output-file requirements.txt requirements.in; \
	fi
	$(PY) -m piptools sync requirements.txt

clean:
	find . -type f -name '*.pyc' -delete
	find . -type d -name '__pycache__' -prune -exec rm -rf {} +

check:
	$(call run_gate,Ruff Check,$(PY) -m ruff check .)
	$(call run_gate,Ruff Format Check,$(PY) -m ruff format --check .)

format:
	$(PY) -m ruff format .

test: check
	$(call run_gate,$(if $(filter 1,$(INTEGRATION)),Pytest (unit + integration),Pytest (unit)),$(PYTEST_INTEGRATION_ENV) $(PY) -m pytest --quiet tests resources services actors)

test-all:
	$(MAKE) check
	$(MAKE) test integration
	$(MAKE) smoke
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

smoke: check
	$(call run_gate,Pytest Smoke,$(PY) -m pytest --quiet \
		actors/agent/tests/test_agent_turn_harness.py \
		tests/integration/test_attention_notify_api_smoke.py \
		resources/adapters/signal/tests/test_signal_adapter_wire_integration.py \
		tests/integration/test_agent_e2e_smoke.py)

docs: $(GLOSSARY_DOC) $(SERVICE_API_DOC) $(HTTP_API_DOC) $(CAPABILITY_DOC) $(DIAGRAM_PNGS)

$(GLOSSARY_DOC): $(GLOSSARY_SRC) $(GLOSSARY_GEN)
	$(PY) $(GLOSSARY_GEN)

$(SERVICE_API_DOC): $(SERVICE_API_SRC) $(SERVICE_API_GEN)
	$(PY) $(SERVICE_API_GEN)

$(HTTP_API_DOC): $(HTTP_API_SRC) $(HTTP_API_GEN) $(HTTP_API_META)
	$(PY) $(HTTP_API_GEN)

$(CAPABILITY_DOC): $(CAPABILITY_SRC) $(CAPABILITY_GEN)
	$(PY) $(CAPABILITY_GEN)

$(DIAGRAM_PNGS): $(DIAGRAM_SRC) $(DIAGRAM_GEN)
	$(DIAGRAM_GEN) $(DIAGRAM_SRC)

up:
	PYTHON_VERSION=$(PYTHON_VERSION) docker compose up --build --detach

down:
	docker compose down

outline:
	@tree -d -I __pycache__ -I tests -I data -I migrations packages resources services actors
