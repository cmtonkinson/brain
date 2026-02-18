SHELL         := /bin/bash
PROTO_DIR     := protos
GENERATED_DIR := generated
PROTO_FILES   := $(shell find $(PROTO_DIR) -type f -name '*.proto' | sort)
PROTO_STAMP   := $(GENERATED_DIR)/.proto-stamp

.PHONY: all deps clean build test migrate

all: clean build test

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

test: build
	@if command -v pytest >/dev/null 2>&1; then \
		pytest -q tests; \
	else \
		echo "No test runner found."; \
		exit 1; \
	fi

migrate:
	@python -c "import alembic, psycopg" >/dev/null 2>&1 || \
		( echo "Missing migration dependencies in current Python environment."; \
		  echo "Install with: make deps"; \
		  exit 1 )
	@BRAIN_POSTGRES__URL="$${BRAIN_POSTGRES__URL:-postgresql+psycopg://brain:brain@localhost:5432/brain}" \
		bash -lc '\
			set -euo pipefail; \
			shopt -s nullglob; \
			for layer in state action control; do \
				for ini in services/$$layer/*/migrations/alembic.ini; do \
					echo "Running migrations: $$ini"; \
					python -m alembic -c "$$ini" upgrade head; \
				done; \
			done'
