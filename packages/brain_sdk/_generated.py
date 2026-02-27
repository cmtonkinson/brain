"""Generated protobuf import bootstrap for Brain SDK."""

from __future__ import annotations

import sys
from pathlib import Path


def ensure_generated_path() -> Path:
    """Ensure repository ``generated/`` path is importable for protobuf stubs."""
    repo_root = Path(__file__).resolve().parents[2]
    generated_dir = repo_root / "generated"
    generated_path = str(generated_dir)
    if generated_dir.is_dir() and generated_path not in sys.path:
        sys.path.insert(0, generated_path)
    return generated_dir


ensure_generated_path()

from brain.action.v1 import language_model_pb2, language_model_pb2_grpc  # noqa: E402
from brain.shared.v1 import (  # noqa: E402
    core_health_pb2,
    core_health_pb2_grpc,
    envelope_pb2,
)
from brain.state.v1 import vault_pb2, vault_pb2_grpc  # noqa: E402

__all__ = [
    "core_health_pb2",
    "core_health_pb2_grpc",
    "envelope_pb2",
    "language_model_pb2",
    "language_model_pb2_grpc",
    "vault_pb2",
    "vault_pb2_grpc",
    "ensure_generated_path",
]
