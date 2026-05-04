"""Behavior tests for the Signal provisioning orchestrator."""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from lib.setup.signal_setup import (
    SetupError,
    SignalNumbers,
    _load_numbers,
    run_setup,
)

BRAIN = "+15551112222"
OPERATOR = "+15553334444"


def _scripted_input(monkeypatch, answers: list[str]) -> None:
    """Drive ``builtins.input`` from a deterministic list of strings."""
    queue = list(answers)

    def fake_input(_prompt: str = "") -> str:
        if not queue:
            raise EOFError("scripted_input exhausted")
        return queue.pop(0)

    monkeypatch.setattr("builtins.input", fake_input)


def _no_sleep(monkeypatch) -> None:
    """Skip the health-poll backoff and fast-forward the monotonic clock."""
    monkeypatch.setattr("lib.setup.signal_setup.time.sleep", lambda _seconds: None)

    ticks = iter(range(10_000))
    monkeypatch.setattr(
        "lib.setup.signal_setup.time.monotonic", lambda: float(next(ticks))
    )


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    """Build an httpx.Client backed by a MockTransport."""
    return httpx.Client(
        base_url="http://signal-api-test:8080",
        transport=httpx.MockTransport(handler),
    )


def test_run_setup_short_circuits_when_already_registered(monkeypatch, capsys):
    """Existing brain_e164 in /v1/accounts → skip captcha + verify, still trust."""
    _no_sleep(monkeypatch)
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(f"{request.method} {request.url.path}")
        if request.url.path == "/v1/health":
            return httpx.Response(200)
        if request.url.path == "/v1/accounts":
            return httpx.Response(200, json=[BRAIN])
        if request.url.path == f"/v1/identities/{BRAIN}/trust/{OPERATOR}":
            return httpx.Response(204)
        raise AssertionError(f"unexpected request: {request.method} {request.url.path}")

    # No prompts should be issued (no captcha, no code).
    monkeypatch.setattr(
        "builtins.input",
        lambda _prompt="": (_ for _ in ()).throw(
            AssertionError("no input should be requested")
        ),
    )

    with _client(handler) as client:
        run_setup(client=client, numbers=SignalNumbers(BRAIN, OPERATOR))

    assert "GET /v1/health" in calls
    assert "GET /v1/accounts" in calls
    assert f"PUT /v1/identities/{BRAIN}/trust/{OPERATOR}" in calls
    out = capsys.readouterr().out
    assert "already registered" in out
    assert "Signal configured" in out


def test_run_setup_happy_path(monkeypatch, capsys):
    """Fresh install path: captcha → register → verify → trust → confirm."""
    _no_sleep(monkeypatch)
    accounts: list[str] = []
    calls: list[tuple[str, str, dict | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = None
        if request.content:
            try:
                body = request.read().decode()
            except Exception:  # noqa: BLE001
                body = "<binary>"
        calls.append((request.method, request.url.path, body))

        if request.url.path == "/v1/health":
            return httpx.Response(200)
        if request.url.path == "/v1/accounts":
            return httpx.Response(200, json=list(accounts))
        if request.url.path == f"/v1/register/{BRAIN}":
            assert "captcha-token-from-browser" in (body or "")
            return httpx.Response(201)
        if request.url.path == f"/v1/register/{BRAIN}/verify/123456":
            accounts.append(BRAIN)
            return httpx.Response(201)
        if request.url.path == f"/v1/identities/{BRAIN}/trust/{OPERATOR}":
            return httpx.Response(204)
        raise AssertionError(f"unexpected request: {request.method} {request.url.path}")

    _scripted_input(
        monkeypatch,
        [
            "signalcaptcha://captcha-token-from-browser",  # prefix-stripped
            "n",  # voice? no → SMS
            "123-456",  # verification code (hyphens stripped)
        ],
    )

    with _client(handler) as client:
        run_setup(client=client, numbers=SignalNumbers(BRAIN, OPERATOR))

    methods_paths = [(m, p) for (m, p, _b) in calls]
    assert ("POST", f"/v1/register/{BRAIN}") in methods_paths
    assert ("POST", f"/v1/register/{BRAIN}/verify/123456") in methods_paths
    assert ("PUT", f"/v1/identities/{BRAIN}/trust/{OPERATOR}") in methods_paths
    out = capsys.readouterr().out
    assert "Signal configured" in out


def test_run_setup_health_failure_raises(monkeypatch):
    """No 2xx from /v1/health within budget → SetupError with hint."""
    _no_sleep(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/health":
            return httpx.Response(503)
        raise AssertionError("setup should not progress past health check")

    with _client(handler) as client:
        with pytest.raises(SetupError, match="did not respond healthy"):
            run_setup(client=client, numbers=SignalNumbers(BRAIN, OPERATOR))


def test_run_setup_register_400_surfaces_decoded_error(monkeypatch):
    """Captcha rejected → SetupError with the API's error message."""
    _no_sleep(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/health":
            return httpx.Response(200)
        if request.url.path == "/v1/accounts":
            return httpx.Response(200, json=[])
        if request.url.path == f"/v1/register/{BRAIN}":
            return httpx.Response(
                400, json={"error": "Captcha required (captcha invalid)"}
            )
        raise AssertionError(f"unexpected: {request.url.path}")

    _scripted_input(monkeypatch, ["bad-captcha-token", "n"])

    with _client(handler) as client:
        with pytest.raises(SetupError, match="Captcha required"):
            run_setup(client=client, numbers=SignalNumbers(BRAIN, OPERATOR))


def test_run_setup_verify_wrong_code_reprompts(monkeypatch, capsys):
    """First verify rejected, second succeeds → orchestrator retries inline."""
    _no_sleep(monkeypatch)
    accounts: list[str] = []
    verify_attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal verify_attempts
        if request.url.path == "/v1/health":
            return httpx.Response(200)
        if request.url.path == "/v1/accounts":
            return httpx.Response(200, json=list(accounts))
        if request.url.path == f"/v1/register/{BRAIN}":
            return httpx.Response(201)
        if request.url.path.startswith(f"/v1/register/{BRAIN}/verify/"):
            verify_attempts += 1
            if request.url.path.endswith("/000000"):
                return httpx.Response(400, json={"error": "Invalid verification code"})
            accounts.append(BRAIN)
            return httpx.Response(201)
        if request.url.path == f"/v1/identities/{BRAIN}/trust/{OPERATOR}":
            return httpx.Response(204)
        raise AssertionError(f"unexpected: {request.url.path}")

    _scripted_input(
        monkeypatch,
        [
            "captcha",
            "n",  # SMS
            "000000",  # wrong
            "y",  # try again
            "123456",  # right
        ],
    )

    with _client(handler) as client:
        run_setup(client=client, numbers=SignalNumbers(BRAIN, OPERATOR))

    assert verify_attempts == 2
    out = capsys.readouterr().out
    assert "verification rejected" in out
    assert "Signal configured" in out


def test_run_setup_trust_failure_warns_but_does_not_raise(monkeypatch, capsys):
    """Non-fatal trust failure prints a warning; the script returns normally."""
    _no_sleep(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/health":
            return httpx.Response(200)
        if request.url.path == "/v1/accounts":
            return httpx.Response(200, json=[BRAIN])
        if request.url.path == f"/v1/identities/{BRAIN}/trust/{OPERATOR}":
            return httpx.Response(
                404, json={"error": "no identity for this number yet"}
            )
        raise AssertionError(f"unexpected: {request.url.path}")

    monkeypatch.setattr("builtins.input", lambda _p="": "")

    with _client(handler) as client:
        run_setup(client=client, numbers=SignalNumbers(BRAIN, OPERATOR))

    err = capsys.readouterr().err
    assert "trust call failed" in err
    assert "no identity for this number yet" in err


def test_load_numbers_reads_secrets_yaml(tmp_path):
    """_load_numbers walks ``*.yaml`` files in the config directory."""
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "secrets.yaml").write_text(
        "signal:\n  receive_e164: '+15551112222'\n"
        "profile:\n  operator:\n    signal_contact_e164: '+15553334444'\n"
    )

    numbers = _load_numbers(config_dir=cfg)

    assert numbers.brain_e164 == "+15551112222"
    assert numbers.operator_e164 == "+15553334444"


def test_load_numbers_raises_when_keys_missing(tmp_path):
    """Both numbers must be present; otherwise SetupError lists what's missing."""
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "secrets.yaml").write_text("signal:\n  receive_e164: '+15551112222'\n")

    with pytest.raises(SetupError, match="signal_contact_e164"):
        _load_numbers(config_dir=cfg)


def test_load_numbers_raises_when_config_dir_absent(tmp_path):
    """Missing config dir → clear "run make install" hint."""
    with pytest.raises(SetupError, match="run `make install`"):
        _load_numbers(config_dir=tmp_path / "does-not-exist")
