"""Unit tests for the capabilities registry JSON."""

import json
import re
from pathlib import Path

CAPABILITY_ID_RE = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")
ALLOWED_STATUSES = {"active", "deprecated"}


def _load_json(path: Path) -> dict:
    """Load JSON from disk into a dict."""
    return json.loads(path.read_text(encoding="utf-8"))


def test_capabilities_registry_ids_are_unique_and_well_formed():
    """Capability IDs are unique and match the expected format."""
    repo_root = Path(__file__).resolve().parents[2]
    registry_path = repo_root / "config" / "capabilities.json"
    data = _load_json(registry_path)

    capabilities = data.get("capabilities", [])
    ids = [entry.get("id") for entry in capabilities]

    assert capabilities, "capabilities.json must list at least one capability"
    assert len(ids) == len(set(ids)), "capability IDs must be unique"

    for cap_id in ids:
        assert cap_id, "capability ID must be present"
        assert CAPABILITY_ID_RE.match(cap_id), f"invalid capability ID: {cap_id}"


def test_capabilities_registry_entries_have_required_fields():
    """Capabilities include required metadata fields."""
    repo_root = Path(__file__).resolve().parents[2]
    registry_path = repo_root / "config" / "capabilities.json"
    data = _load_json(registry_path)

    for entry in data.get("capabilities", []):
        assert entry.get("description"), f"missing description for {entry.get('id')}"
        assert entry.get("group"), f"missing group for {entry.get('id')}"
        status = entry.get("status")
        assert status in ALLOWED_STATUSES, f"invalid status for {entry.get('id')}: {status}"


def test_capabilities_sample_matches_registry():
    """Sample capabilities file matches the canonical registry."""
    repo_root = Path(__file__).resolve().parents[2]
    registry_path = repo_root / "config" / "capabilities.json"
    sample_path = repo_root / "config" / "capabilities.json.sample"

    assert sample_path.exists(), "capabilities.json.sample must exist"
    assert _load_json(registry_path) == _load_json(sample_path)
