"""Unit tests for Code-Mode destructive op detection."""

from services.code_mode import _DESTRUCTIVE_KEYWORDS, _detect_destructive_ops


def test_detect_destructive_ops_flags_expected_calls() -> None:
    """Destructive call detection flags expected methods."""
    code = "repo.commit()\nfs.remove('x')\nnoop.read()"
    hits = _detect_destructive_ops(code, _DESTRUCTIVE_KEYWORDS)

    assert any("commit" in hit for hit in hits)
    assert any("remove" in hit for hit in hits)
    assert all("read" not in hit for hit in hits)
