"""List all slash commands available via operator channels."""


def execute() -> str:
    """Return formatted help text for all registered slash commands."""
    from lib.sdk.client import BrainSdkClient

    brain_client = BrainSdkClient(source="slash-help", principal="operator")
    caps = brain_client.describe_ops()

    slash_caps = sorted(
        (c for c in caps if c.slash_command_name),
        key=lambda c: c.slash_command_name or "",
    )
    if not slash_caps:
        return "No slash commands registered."

    lines = ["Available commands:"]
    for cap in slash_caps:
        line = f"  /{cap.slash_command_name}"
        if cap.slash_command_aliases:
            aliases = ", ".join(f"/{a}" for a in cap.slash_command_aliases)
            line += f" (aliases: {aliases})"
        desc = cap.slash_command_description or cap.summary
        if desc:
            line += f" \u2014 {desc}"
        lines.append(line)
    return "\n".join(lines)
