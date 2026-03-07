"""One-command in-process end-to-end agent smoke runner."""

from __future__ import annotations

from pathlib import Path
import sys
import tempfile

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.helpers.inprocess_core_smoke import run_agent_e2e_smoke  # noqa: E402


def main() -> int:
    """Run one inbound Signal webhook through the in-process agent stack."""
    with tempfile.TemporaryDirectory(prefix="brain-smoke-e2e-") as tmp_dir:
        result = run_agent_e2e_smoke(tmp_path=Path(tmp_dir))
    print(f"inbound_status={result.inbound_status_code}")
    print(f"response_text={result.response_text}")
    for message in result.outbound_signal_messages:
        print(message)
    if result.inbound_status_code != 202:
        return 1
    if result.response_text != "assistant reply":
        return 1
    if len(result.outbound_signal_messages) != 1:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
