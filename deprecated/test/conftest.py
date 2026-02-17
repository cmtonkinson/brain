"""Pytest configuration for Brain test suite."""

import os
import sys
from collections.abc import Generator
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def _ensure_test_env() -> None:
    """Seed required environment variables for tests."""
    os.environ.setdefault("OBSIDIAN_API_KEY", "test-key")
    os.environ.setdefault("OBSIDIAN_VAULT_PATH", "/tmp/brain-test-vault")
    os.environ.setdefault("ALLOWED_SENDERS", '["+15551234567"]')
    os.environ.setdefault("USER", "test-user")


_ensure_test_env()

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))


@pytest.fixture()
def sqlite_session_factory() -> Generator[sessionmaker, None, None]:
    """Provide a sqlite session factory and ensure engine cleanup."""
    from models import Base

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    yield factory
    engine.dispose()
