SHELL           := /bin/bash
VENV 						:= .venv
VENV_PY         := $(VENV)/bin/python
PY 							:= $(if $(wildcard $(VENV_PY)),$(VENV_PY),python3)
PYTHON_VERSION  := $(shell cut -d. -f1,2 .python-version)
GENERATED_DIR   := generated
GLOSSARY_SRC    := docs/glossary.yaml
GLOSSARY_DOC    := docs/glossary.md
GLOSSARY_GEN    := scripts/generate_glossary_docs.py
SERVICE_API_DOC := docs/service-api.md
SERVICE_API_GEN := scripts/generate_service_api_docs.py
SERVICE_API_SRC := $(shell find services -type f -path 'services/*/*/service.py' | sort)
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

.PHONY: all deps deps-upgrade clean build check format test docs up down integration

all: deps clean build test docs

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
	rm -rf $(GENERATED_DIR)
	find . -type f -name '*.pyc' -delete
	find . -type d -name '__pycache__' -prune -exec rm -rf {} +

build:

check:
	$(PY) -m ruff check .
	$(PY) -m ruff format --check .

format:
	$(PY) -m ruff format .

test: check
	$(PYTEST_INTEGRATION_ENV) $(PY) -m pytest --quiet tests resources services actors

integration:
	:

docs: $(GLOSSARY_DOC) $(SERVICE_API_DOC) $(DIAGRAM_PNGS)

$(GLOSSARY_DOC): $(GLOSSARY_SRC) $(GLOSSARY_GEN)
	$(PY) $(GLOSSARY_GEN)

$(SERVICE_API_DOC): $(SERVICE_API_SRC) $(SERVICE_API_GEN)
	$(PY) $(SERVICE_API_GEN)

$(DIAGRAM_PNGS): $(DIAGRAM_SRC) $(DIAGRAM_GEN)
	$(DIAGRAM_GEN) $(DIAGRAM_SRC)

up:
	PYTHON_VERSION=$(PYTHON_VERSION) docker compose up --build --detach

down:
	docker compose down

outline:
	@tree -d -I tests -I __pycache__ -I data -I migrations packages resources services actors
