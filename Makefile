SHELL           := /bin/bash
PROTO_DIR       := protos
GENERATED_DIR   := generated
PROTO_FILES     := $(shell find $(PROTO_DIR) -type f -name '*.proto' | sort)
PROTO_STAMP     := $(GENERATED_DIR)/.proto-stamp
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

.PHONY: all deps clean build check format test docs migrate up down

all: deps clean build test docs

deps:
	@pip install --requirement requirements.txt

clean:
	@rm -rf $(GENERATED_DIR)
	@find . -type f -name '*.pyc' -delete
	@find . -type d -name '__pycache__' -prune -exec rm -rf {} +

build: $(PROTO_STAMP)

$(PROTO_STAMP): $(PROTO_FILES)
	@mkdir -p $(GENERATED_DIR)
	@python -c "import grpc_tools.protoc" >/dev/null 2>&1 || \
		( echo "Missing grpcio-tools in current Python environment."; \
		  echo "Install with: pip install grpcio-tools"; \
		  exit 1 )
	@python -m grpc_tools.protoc \
		-I $(PROTO_DIR) \
		--python_out=$(GENERATED_DIR) \
		--grpc_python_out=$(GENERATED_DIR) \
		$(PROTO_FILES)
	@python -m compileall -q $(GENERATED_DIR)
	@touch $(PROTO_STAMP)

check:
	@python -c "import ruff" >/dev/null 2>&1 || \
		( echo "Missing ruff in current Python environment."; \
		  echo "Install with: make deps"; \
		  exit 1 )
	@ruff check .
	@ruff format --check .

format:
	@python -c "import ruff" >/dev/null 2>&1 || \
		( echo "Missing ruff in current Python environment."; \
		  echo "Install with: make deps"; \
		  exit 1 )
	@ruff format .

test: build check
	@if command -v pytest >/dev/null 2>&1; then \
		pytest -q tests services resources; \
	else \
		echo "No test runner found."; \
		exit 1; \
	fi

docs: $(GLOSSARY_DOC) $(SERVICE_API_DOC) $(DIAGRAM_PNGS)

$(GLOSSARY_DOC): $(GLOSSARY_SRC) $(GLOSSARY_GEN)
	@python $(GLOSSARY_GEN)

$(SERVICE_API_DOC): $(SERVICE_API_SRC) $(SERVICE_API_GEN)
	@python $(SERVICE_API_GEN)

$(DIAGRAM_PNGS): $(DIAGRAM_SRC) $(DIAGRAM_GEN)
	@$(DIAGRAM_GEN) $(DIAGRAM_SRC)

migrate:
	@python -c "import alembic, psycopg" >/dev/null 2>&1 || \
		( echo "Missing migration dependencies in current Python environment."; \
		  echo "Install with: make deps"; \
		  exit 1 )
	@bash -lc '\
		set -euo pipefail; \
		if [ -z "$${BRAIN_POSTGRES__URL:-}" ]; then \
			export BRAIN_POSTGRES__URL="$$(python -c '\''from packages.brain_shared.config import load_config; print(str(load_config().get("postgres", {}).get("url", "")).strip())'\'')"; \
		fi; \
		if [ -z "$$BRAIN_POSTGRES__URL" ]; then \
			echo "BRAIN_POSTGRES__URL resolved to empty value; set postgres.url in config or export BRAIN_POSTGRES__URL."; \
			exit 1; \
		fi; \
		shopt -s nullglob; \
		python -m resources.substrates.postgres.bootstrap; \
		for layer in state action control; do \
			for ini in services/$$layer/*/migrations/alembic.ini; do \
				echo "Running migrations: $$ini"; \
				python -m alembic -c "$$ini" upgrade head; \
			done; \
		done'

up:
	@docker compose up --detach --build

down:
	@docker compose down
