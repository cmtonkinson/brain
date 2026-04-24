"""One-command fast smoke runner for the agent outbound turn path."""

from __future__ import annotations

import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.helpers.agent_turn_harness import (  # noqa: E402
    AgentTurnScenario,
    run_agent_turn_scenario,
)


def main() -> int:
    """Run one deterministic in-process agent turn and print captured calls."""
    result = run_agent_turn_scenario(AgentTurnScenario())
    print(f"response_text={result.response_text}")
    for call in result.calls:
        print(f"{call.method} {call.path} {json.dumps(call.body, sort_keys=True)}")

    invoke_call = result.calls[-1]
    invocation_id = str(invoke_call.body.get("invocation_id", "")).strip()
    if invoke_call.path != "/ops/invoke":
        print("expected final call to /ops/invoke", file=sys.stderr)
        return 1
    if invocation_id == "":
        print("expected non-empty invocation_id", file=sys.stderr)
        return 1
    if invoke_call.body.get("op_id") != "relay-notify":
        print("expected relay-notify invoke", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
