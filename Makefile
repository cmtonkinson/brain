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

ifneq (,$(filter integration,$(MAKECMDGOALS)))
INTEGRATION := 1
endif

ifeq ($(INTEGRATION),1)
PYTEST_INTEGRATION_ENV := BRAIN_RUN_INTEGRATION_REAL=1
endif

.PHONY: all deps deps-upgrade clean check format test docs up down integration outline smoke smoke-e2e

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
	$(PY) -m ruff check .
	$(PY) -m ruff format --check .

format:
	$(PY) -m ruff format .

test: check
	$(PYTEST_INTEGRATION_ENV) $(PY) -m pytest --quiet tests resources services actors

integration:
	:

smoke-e2e:
	$(PY) scripts/smoke_agent_e2e.py

smoke: check
	$(PY) -m pytest --quiet \
		actors/agent/tests/test_agent_turn_harness.py \
		tests/integration/test_attention_notify_api_smoke.py \
		resources/adapters/signal/tests/test_signal_adapter_wire_integration.py \
		tests/integration/test_agent_e2e_smoke.py

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
