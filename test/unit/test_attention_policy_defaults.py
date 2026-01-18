"""Unit tests for default attention policy set."""

from attention.policy_defaults import default_attention_policies


def test_default_attention_policies_include_approval_routing() -> None:
    """Ensure default policies include approval routing."""
    policies = default_attention_policies()

    assert policies
    assert any(policy.policy_id == "approval-requests-signal" for policy in policies)
