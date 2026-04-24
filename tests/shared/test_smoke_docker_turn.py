"""Regression coverage for the Docker smoke stack configuration."""

from __future__ import annotations

from scripts.smoke_docker_turn import _build_smoke_environment


def test_build_smoke_environment_uses_dynamic_host_ports() -> None:
    """The hermetic smoke stack must not collide with the default dev ports."""
    env = _build_smoke_environment()

    assert env["BRAIN_CORE__PORT_BIND"] == "127.0.0.1::8898"
    assert env["BRAIN_POSTGRES__PORT_BIND"] == "127.0.0.1::5432"
    assert env["BRAIN_VALKEY__PORT_BIND"] == "127.0.0.1::6379"
    assert env["BRAIN_QDRANT__PORT_BIND"] == "127.0.0.1::6333"
