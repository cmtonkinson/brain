"""Hermetic Docker Compose smoke for one real boot and agent turn."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from typing import Any

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILE = REPO_ROOT / "docker-compose.yaml"
PYTHON_VERSION = (REPO_ROOT / ".python-version").read_text(encoding="utf-8").strip()
SIGNAL_RECEIVE_PAYLOAD = json.dumps(
    {
        "account": "+17175371552",
        "envelope": {
            "source": "+16104257807",
            "sourceDevice": 1,
            "timestamp": 1730000000000,
            "dataMessage": {"message": "hello"},
        },
    }
)
EXPECTED_REPLY = "assistant reply"


class _SmokeFailure(RuntimeError):
    """Raised when the Docker smoke invariants are not satisfied."""


def _run(
    *args: str,
    env: dict[str, str],
    input_text: str | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run one subprocess command from the repository root."""
    return subprocess.run(
        args,
        cwd=REPO_ROOT,
        env=env,
        input=input_text,
        text=True,
        capture_output=True,
        check=check,
    )


def _compose(
    env: dict[str, str],
    override_file: Path,
    *compose_args: str,
    input_text: str | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run one docker compose command with the generated override file."""
    return _run(
        "docker",
        "compose",
        "-f",
        str(COMPOSE_FILE),
        "-f",
        str(override_file),
        *compose_args,
        env=env,
        input_text=input_text,
        check=check,
    )


def _write_smoke_configs(*, config_dir: Path) -> None:
    """Write hermetic Brain config files used only by the smoke stack."""
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "generated").mkdir(parents=True, exist_ok=True)
    (config_dir / "core.yaml").write_text(
        "\n".join(
            [
                "logging:",
                "  level: INFO",
                "  json_output: true",
                "profile:",
                "  operator_name: Operator",
                "  brain_name: Brain",
                "  brain_verbosity: normal",
                "  operator:",
                "    signal_contact_e164: '+16104257807'",
                "service:",
                "  switchboard:",
                "    callback_register_max_retries: 2",
                "    callback_register_retry_delay_seconds: 0.2",
                "  language_model:",
                "    document_embedding:",
                "      provider: ollama",
                "      model: mxbai-embed-large",
                "      dimensions: 1024",
                "    capability_embedding:",
                "      provider: ollama",
                "      model: mxbai-embed-large",
                "      dimensions: 1024",
                "    quick:",
                "      provider: anthropic",
                "      model: claude-haiku-4-5-20251001",
                "    standard:",
                "      provider: anthropic",
                "      model: claude-sonnet-4-6-20251001",
                "    deep:",
                "      provider: anthropic",
                "      model: claude-opus-4-7",
            ]
        ),
        encoding="utf-8",
    )
    (config_dir / "resources.yaml").write_text(
        "\n".join(
            [
                "substrate:",
                "  postgres:",
                "    url: postgresql+psycopg://brain:brain@postgres:5432/brain",
                "  obsidian:",
                "    base_url: http://obsidian-fake:27123",
                "adapter:",
                "  signal:",
                "    base_url: http://signal-api:8080",
                "    receive_e164: '+17175371552'",
                "  llm:",
                "    providers:",
                "      anthropic:",
                "        api_base: http://llm-fake:4000",
                "        api_key: smoke-key",
                "      voyage:",
                "        api_base: http://llm-fake:4000",
                "        api_key: smoke-key",
                "  utcp_code_mode:",
                "    code_mode:",
                "      defaults:",
                "        call_template_type: mcp",
                "      servers:",
                "        smoke:",
                "          command: python",
                "          args: ['-c', 'print(\"smoke\")']",
            ]
        ),
        encoding="utf-8",
    )
    (config_dir / "actors.yaml").write_text(
        "\n".join(
            [
                "logging:",
                "  level: INFO",
                "  json_output: true",
            ]
        ),
        encoding="utf-8",
    )


def _write_override_file(
    *,
    override_file: Path,
    tmp_root: Path,
    config_dir: Path,
) -> None:
    """Write one smoke-specific compose override file."""
    fake_signal_state = tmp_root / "fake-signal"
    fake_llm_state = tmp_root / "fake-llm"
    fake_obsidian_state = tmp_root / "fake-obsidian"
    postgres_data = tmp_root / "postgres"
    redis_data = tmp_root / "redis"
    qdrant_data = tmp_root / "qdrant"
    generated_dir = config_dir / "generated"
    for path in (
        fake_signal_state,
        fake_llm_state,
        fake_obsidian_state,
        postgres_data,
        redis_data,
        qdrant_data,
    ):
        path.mkdir(parents=True, exist_ok=True)

    base_build = {
        "context": str(REPO_ROOT),
        "dockerfile": "Dockerfile",
        "args": {"PYTHON_VERSION": PYTHON_VERSION},
    }
    fake_http_image = "brain-smoke-http-fake:latest"
    health_command = lambda url: [  # noqa: E731
        "CMD",
        "python",
        "-c",
        (f"import urllib.request;urllib.request.urlopen('{url}', timeout=1).read()"),
    ]
    override = {
        "services": {
            "brain-core": {
                "restart": "no",
                "volumes": [
                    f"{config_dir}:/app/config:ro",
                    f"{generated_dir}:/app/config/generated:rw",
                    f"{REPO_ROOT / 'scripts' / 'healthcheck-core.sh'}:/usr/local/bin/brain-healthcheck:ro",
                ],
                "depends_on": {
                    "postgres": {"condition": "service_healthy"},
                    "redis": {"condition": "service_healthy"},
                    "qdrant": {"condition": "service_started"},
                    "llm-fake": {"condition": "service_healthy"},
                    "obsidian-fake": {"condition": "service_healthy"},
                },
            },
            "brain-agent": {
                "restart": "no",
                "volumes": [
                    f"{config_dir}:/app/config:ro",
                    f"{generated_dir}:/app/config/generated:rw",
                    f"{REPO_ROOT / 'scripts' / 'healthcheck-agent.sh'}:/usr/local/bin/brain-healthcheck:ro",
                ],
            },
            "postgres": {
                "restart": "no",
                "volumes": [f"{postgres_data}:/var/lib/postgresql/data"],
            },
            "redis": {
                "restart": "no",
                "volumes": [f"{redis_data}:/data"],
            },
            "qdrant": {
                "restart": "no",
                "volumes": [f"{qdrant_data}:/qdrant/storage"],
            },
            "signal-api": {
                "image": fake_http_image,
                "build": base_build,
                "restart": "no",
                "depends_on": {
                    "brain-core": {"condition": "service_healthy"},
                },
                "entrypoint": [
                    "python",
                    "/app/scripts/smoke_fake_http_service.py",
                    "signal",
                    "--host",
                    "0.0.0.0",
                    "--port",
                    "8080",
                    "--state-dir",
                    "/state",
                ],
                "volumes": [
                    f"{fake_signal_state}:/state:rw",
                ],
                "healthcheck": {
                    "test": health_command("http://127.0.0.1:8080/v1/health"),
                    "interval": "2s",
                    "timeout": "2s",
                    "retries": 20,
                },
            },
            "llm-fake": {
                "image": fake_http_image,
                "build": base_build,
                "restart": "no",
                "entrypoint": [
                    "python",
                    "/app/scripts/smoke_fake_http_service.py",
                    "llm",
                    "--host",
                    "0.0.0.0",
                    "--port",
                    "4000",
                    "--state-dir",
                    "/state",
                ],
                "volumes": [
                    f"{fake_llm_state}:/state:rw",
                ],
                "healthcheck": {
                    "test": health_command("http://127.0.0.1:4000/health"),
                    "interval": "2s",
                    "timeout": "2s",
                    "retries": 20,
                },
            },
            "obsidian-fake": {
                "image": fake_http_image,
                "build": base_build,
                "restart": "no",
                "entrypoint": [
                    "python",
                    "/app/scripts/smoke_fake_http_service.py",
                    "obsidian",
                    "--host",
                    "0.0.0.0",
                    "--port",
                    "27123",
                    "--state-dir",
                    "/state",
                ],
                "volumes": [
                    f"{fake_obsidian_state}:/state:rw",
                ],
                "healthcheck": {
                    "test": health_command("http://127.0.0.1:27123/health"),
                    "interval": "2s",
                    "timeout": "2s",
                    "retries": 20,
                },
            },
        }
    }
    override_file.write_text(
        yaml.safe_dump(override, sort_keys=False), encoding="utf-8"
    )


def _wait_for_core_health(*, env: dict[str, str], override_file: Path) -> None:
    """Wait until Core health succeeds over the published TCP endpoint."""
    deadline = time.monotonic() + 120.0
    while time.monotonic() < deadline:
        result = _compose(
            env,
            override_file,
            "exec",
            "-T",
            "brain-core",
            "curl",
            "--silent",
            "--fail",
            "http://127.0.0.1:8898/health",
            check=False,
        )
        if result.returncode == 0:
            payload = json.loads(result.stdout)
            if payload.get("ready") is True:
                return
        time.sleep(1.0)
    raise _SmokeFailure("timed out waiting for core health")


def _wait_for_agent_running(*, env: dict[str, str], override_file: Path) -> None:
    """Wait until the agent container is running and not restarting."""
    deadline = time.monotonic() + 60.0
    while time.monotonic() < deadline:
        container_id = _compose(
            env,
            override_file,
            "ps",
            "-q",
            "brain-agent",
            check=False,
        ).stdout.strip()
        if container_id != "":
            inspect = _run(
                "docker",
                "inspect",
                "-f",
                "{{.State.Running}} {{.State.Restarting}}",
                container_id,
                env=env,
                check=False,
            )
            if inspect.returncode == 0 and inspect.stdout.strip() == "true false":
                return
        time.sleep(1.0)
    raise _SmokeFailure("timed out waiting for brain-agent to stay running")


def _inject_signal_message(
    *, env: dict[str, str], override_file: Path
) -> dict[str, Any]:
    """Queue one inbound Signal payload on the fake Signal provider."""
    program = (
        "import httpx, json, sys;"
        "payload = sys.stdin.read();"
        "response = httpx.post("
        "'http://signal-api:8080/testing/inject-receive',"
        "content=payload,"
        "headers={'Content-Type': 'application/json'},"
        "timeout=10.0);"
        "print(json.dumps({'status_code': response.status_code, 'body': response.json()}))"
    )
    result = _compose(
        env,
        override_file,
        "exec",
        "-T",
        "brain-core",
        "python",
        "-c",
        program,
        input_text=SIGNAL_RECEIVE_PAYLOAD,
    )
    payload = json.loads(result.stdout.strip())
    if payload["status_code"] != 200:
        raise _SmokeFailure(f"signal injection failed: {payload}")
    return payload


def _read_json_file(path: Path) -> list[object]:
    """Read one JSON array file or return an empty list when absent."""
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise _SmokeFailure(f"{path} did not contain a JSON array")
    return payload


def _wait_for_outbound_send(*, fake_signal_state: Path) -> list[object]:
    """Wait until exactly one outbound send has been captured by the fake Signal."""
    deadline = time.monotonic() + 60.0
    path = fake_signal_state / "sent_messages.json"
    while time.monotonic() < deadline:
        values = _read_json_file(path)
        if len(values) == 1:
            return values
        time.sleep(1.0)
    raise _SmokeFailure("timed out waiting for outbound signal send")


def _psql_scalar(
    *,
    env: dict[str, str],
    override_file: Path,
    sql: str,
) -> str:
    """Run one scalar SQL query inside the transient Postgres container."""
    result = _compose(
        env,
        override_file,
        "exec",
        "-T",
        "postgres",
        "psql",
        "-U",
        "brain",
        "-d",
        "brain",
        "-Atqc",
        sql,
    )
    return result.stdout.strip()


def _assert_database_evidence(*, env: dict[str, str], override_file: Path) -> None:
    """Assert MAS and LMS persisted the handled turn and raw model call."""
    outbound_turn_count = int(
        _psql_scalar(
            env=env,
            override_file=override_file,
            sql=(
                "SELECT COUNT(*) FROM service_memory_authority.turn "
                "WHERE direction = 'outbound';"
            ),
        )
    )
    if outbound_turn_count != 1:
        raise _SmokeFailure(
            f"expected exactly one outbound MAS turn, found {outbound_turn_count}"
        )

    outbound_content = _psql_scalar(
        env=env,
        override_file=override_file,
        sql=(
            "SELECT content FROM service_memory_authority.turn "
            "WHERE direction = 'outbound' "
            "ORDER BY created_at DESC LIMIT 1;"
        ),
    )
    if outbound_content != EXPECTED_REPLY:
        raise _SmokeFailure(f"unexpected outbound content: {outbound_content!r}")

    lms_call_count = int(
        _psql_scalar(
            env=env,
            override_file=override_file,
            sql=(
                "SELECT COUNT(*) FROM service_language_model.call_audits "
                "WHERE operation = 'chat_with_tools' "
                "AND request_json IS NOT NULL "
                "AND response_json IS NOT NULL;"
            ),
        )
    )
    if lms_call_count < 1:
        raise _SmokeFailure("expected at least one LMS audit row with raw payloads")


def _print_diagnostics(*, env: dict[str, str], override_file: Path) -> None:
    """Emit compose ps and logs to aid debugging one failing smoke run."""
    ps = _compose(env, override_file, "ps", check=False)
    logs = _compose(env, override_file, "logs", "--no-color", check=False)
    print("=== docker compose ps ===")
    print(ps.stdout or ps.stderr)
    print("=== docker compose logs ===")
    print(logs.stdout or logs.stderr)


def _build_smoke_environment() -> dict[str, str]:
    """Build one isolated compose environment for the Docker smoke stack."""
    return {
        **os.environ,
        "BRAIN_CORE_PORT_BIND": "127.0.0.1::8898",
        "BRAIN_POSTGRES_PORT_BIND": "127.0.0.1::5432",
        "BRAIN_REDIS_PORT_BIND": "127.0.0.1::6379",
        "BRAIN_QDRANT_PORT_BIND": "127.0.0.1::6333",
        "PYTHON_VERSION": PYTHON_VERSION.split(".")[0]
        + "."
        + PYTHON_VERSION.split(".")[1],
        "COMPOSE_PROJECT_NAME": f"brain-smoke-{int(time.time())}",
    }


def main() -> int:
    """Run one full boot-and-turn smoke against the real Compose stack."""
    with tempfile.TemporaryDirectory(prefix="brain-smoke-docker-") as tmp:
        tmp_root = Path(tmp)
        config_dir = tmp_root / "config"
        override_file = tmp_root / "docker-compose.smoke.yaml"
        fake_signal_state = tmp_root / "fake-signal"
        _write_smoke_configs(config_dir=config_dir)
        _write_override_file(
            override_file=override_file,
            tmp_root=tmp_root,
            config_dir=config_dir,
        )

        env = _build_smoke_environment()

        try:
            _compose(env, override_file, "up", "--build", "--detach")
            _wait_for_core_health(env=env, override_file=override_file)
            _wait_for_agent_running(env=env, override_file=override_file)
            inbound = _inject_signal_message(env=env, override_file=override_file)
            sends = _wait_for_outbound_send(fake_signal_state=fake_signal_state)
            _assert_database_evidence(env=env, override_file=override_file)
        except Exception:
            _print_diagnostics(env=env, override_file=override_file)
            raise
        finally:
            _compose(
                env,
                override_file,
                "down",
                "--volumes",
                "--remove-orphans",
                check=False,
            )

    message = sends[0]
    if not isinstance(message, dict):
        raise _SmokeFailure("fake signal capture did not contain an object payload")
    if message.get("message") != EXPECTED_REPLY:
        raise _SmokeFailure(f"unexpected outbound reply payload: {message}")

    print(json.dumps(inbound, sort_keys=True))
    print(json.dumps(message, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
