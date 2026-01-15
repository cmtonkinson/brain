import os
import sys
from pathlib import Path


def _ensure_test_env() -> None:
    os.environ.setdefault("OBSIDIAN_API_KEY", "test-key")
    os.environ.setdefault("OBSIDIAN_VAULT_PATH", "/tmp/brain-test-vault")
    os.environ.setdefault("ALLOWED_SENDERS", '["+15551234567"]')
    os.environ.setdefault("USER", "test-user")


_ensure_test_env()

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
