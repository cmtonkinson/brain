"""Domain contracts for Execution manifest and invocation APIs."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from lib.shared.auth.slash_authenticity import SlashAuthenticityProof
from lib.shared.op_classification import OpApproval, OpEffect
from services.effect.execution.schema import expand_schema


class OpInvocationMetadata(BaseModel):
    """Invocation metadata supplied by Execution callers for policy and auditing."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    actor: str = Field(min_length=1)
    source: str = Field(min_length=1)
    channel: str = Field(min_length=1)
    invocation_id: str = Field(min_length=1)
    parent_invocation_id: str = ""
    confirmed: bool = False
    approval_token: str = ""
    reply_to_proposal_token: str = ""
    reaction_to_proposal_token: str = ""
    message_text: str = ""
    slash_authenticity: SlashAuthenticityProof | None = None


class OpInvokeResult(BaseModel):
    """Output payload returned by Execution invoke operations."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    op_id: str
    op_version: str
    output: dict[str, Any] | None = None
    policy_decision_id: str
    policy_regime_id: str
    policy_allowed: bool
    policy_reason_codes: tuple[str, ...]
    policy_obligations: tuple[str, ...]
    proposal_token: str = ""


class ExecutionHealthStatus(BaseModel):
    """Execution health payload and registry counters."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    service_ready: bool
    policy_ready: bool
    discovered_ops: int
    invocation_audit_rows: int
    detail: str


class OpExecutionResponse(BaseModel):
    """Internal execution result type used by runtime handlers."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    output: dict[str, Any] | None = None


class PipelineStep(BaseModel):
    """One pipeline step, optionally with explicit input remapping."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    op: str = Field(
        min_length=1,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
    )
    input_mapping: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_input_mapping(self) -> PipelineStep:
        """Require non-empty consumer and producer field names."""
        for consumer_field, producer_field in self.input_mapping.items():
            if not consumer_field:
                raise ValueError(
                    "pipeline input_mapping consumer fields must be non-empty"
                )
            if not producer_field:
                raise ValueError(
                    "pipeline input_mapping producer fields must be non-empty"
                )
        return self

    @classmethod
    def from_entry(cls, entry: str | PipelineStep) -> PipelineStep:
        """Normalize one pipeline entry to the object form."""
        if isinstance(entry, cls):
            return entry
        return cls(op=entry)


class ToolConfig(BaseModel):
    """Surface configuration for tool invocation via the LLM agent."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    description: str | None = None
    """LLM-facing tool description. Defaults to manifest summary when absent."""


class JobConfig(BaseModel):
    """Surface configuration for job invocation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    description: str | None = None
    """Human-facing job description. Defaults to manifest summary when absent."""


class SlashCommandConfig(BaseModel):
    """Surface configuration for slash command invocation via operator channels."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str | None = None
    """Command token without the leading slash. Defaults to op_id when absent."""

    description: str | None = None
    """Help text shown in /help output. Defaults to manifest summary when absent."""

    aliases: tuple[str, ...] = ()
    """Additional command tokens that resolve to the same op."""


class OpManifestBase(BaseModel):
    """Immutable op manifest metadata shared by all op kinds."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    op_id: str = Field(min_length=1, pattern=r"^[a-z0-9]+(?:-{1,2}[a-z0-9]+)*$")
    kind: str
    owner_service_id: str | None = Field(
        default=None,
        pattern=r"^[a-z][a-z0-9_]{1,62}$",
    )
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    summary: str = Field(min_length=1)
    enabled: bool = True
    effect: OpEffect = "read"
    approval: OpApproval = "never"
    required_ops: tuple[str, ...] = ()
    input_schema: dict[str, Any] | None = None
    output_schema: dict[str, Any] | None = None
    simple_output_path: str | None = None
    tool: ToolConfig | None = None
    job: JobConfig | None = None
    slash_command: SlashCommandConfig | None = None

    @model_validator(mode="before")
    @classmethod
    def _expand_manifest_schemas(cls, value: Any) -> Any:
        """Expand manifest schema shorthand with kind-specific alias rules."""
        if not isinstance(value, dict):
            return value

        expanded = dict(value)
        allow_field_aliases = expanded.get("kind") == "pipeline"

        for schema_field in ("input_schema", "output_schema"):
            expanded[schema_field] = expand_schema(
                expanded.get(schema_field),
                allow_field_aliases=allow_field_aliases,
            )
        return expanded


class NativeOpManifest(OpManifestBase):
    """Manifest schema for a native or MCP op package."""

    kind: Literal["native", "mcp"]
    call_target: str = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_required_ops(self) -> NativeOpManifest:
        """Reject explicit sub-op dependencies for thin op wrappers."""
        if self.required_ops:
            raise ValueError("required_ops is only allowed for logic ops")
        return self


class CompoundOpManifest(OpManifestBase):
    """Manifest schema for a compound (logic or pipeline) op package."""

    kind: Literal["logic", "pipeline"]
    pipeline: tuple[str | PipelineStep, ...] = ()
    entrypoint: str = "execute.py"

    @model_validator(mode="after")
    def _validate_required_ops(self) -> CompoundOpManifest:
        """Allow required_ops only for non-declarative logic ops."""
        if self.kind == "pipeline" and self.required_ops:
            raise ValueError("required_ops is only allowed for logic ops")
        return self


OpManifest = NativeOpManifest | CompoundOpManifest


class OpPolicySummary(BaseModel):
    """Policy decision summary included in Execution responses and audit entries."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    decision_id: str
    policy_regime_id: str
    allowed: bool
    reason_codes: tuple[str, ...]
    obligations: tuple[str, ...]
    proposal_token: str = ""


class OpDescriptor(BaseModel):
    """Agent-facing descriptor for one registered op.

    Contains everything a Tier 3 agent needs to A) present the op as an
    LLM tool call and B) construct a valid ``invoke_op`` call if the
    LLM selects it.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    op_id: str
    kind: str
    version: str
    summary: str
    input_schema: dict[str, Any] | None
    output_schema: dict[str, Any] | None
    simple_output_path: str | None
    effect: OpEffect
    approval: OpApproval
    required_ops: tuple[str, ...]
    slash_command_name: str | None = None
    """Resolved slash command token. None when the op has no slash binding."""
    slash_command_aliases: tuple[str, ...] = ()
    """Additional slash command tokens that resolve to this op."""
    slash_command_description: str | None = None
    """Resolved slash command help text. None when the op has no slash binding."""


class OpSearchHit(BaseModel):
    """Compact discovery result for one semantically matched op."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    op_id: str
    required_params: tuple[str, ...]
    summary: str


class ToolSystemHint(BaseModel):
    """Compact Agent-facing hint for one system reachable through tools."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    system_id: str
    label: str
    summary: str
    kind: Literal["core", "mcp"]
    ready: bool | None = None
    tool_count: int | None = None
    pending_tool_count: int | None = None


class OpDiscoveryStateRow(BaseModel):
    """Durable Execution-owned state for one indexed op discovery document."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    op_id: str
    content_digest: str
    chunk_ordinal: int


class DynamicOpClassificationRow(BaseModel):
    """Persisted observed-definition and optional classification for one dynamic op."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    op_id: str
    source_kind: str
    source_ref: str
    definition_digest: str
    summary: str
    input_schema: dict[str, Any] | None = None
    output_schema: dict[str, Any] | None = None
    effect: OpEffect | None = None
    approval: OpApproval | None = None


class OpInvocationAuditRow(BaseModel):
    """Append-only invocation audit record owned by Execution Service."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    audit_id: str
    envelope_id: str
    trace_id: str
    parent_id: str
    invocation_id: str
    parent_invocation_id: str
    actor: str
    source: str
    channel: str
    op_id: str
    op_version: str
    policy_decision_id: str
    policy_regime_id: str
    allowed: bool
    reason_codes: tuple[str, ...]
    proposal_token: str
    created_at: datetime
