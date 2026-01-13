"""Configuration management for Brain assistant."""

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, model_validator


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # LLM Configuration
    anthropic_api_key: str | None = None
    
    # Obsidian Configuration
    obsidian_api_key: str
    obsidian_url: str = "http://host.docker.internal:27123"
    obsidian_vault_path: str
    
    # Database Configuration
    database_url: str | None = None
    postgres_password: str | None = None
    
    # Service URLs
    qdrant_url: str = "http://qdrant:6333"
    redis_url: str = "redis://redis:6379"
    ollama_url: str = "http://host.docker.internal:11434"
    signal_api_url: str = "http://signal-api:8080"
    
    # User Context
    user: str = "user"

    # LLM Configuration (expand the existing anthropic_api_key section)
    litellm_model: str = "claude-sonnet-4-20250514"  # Default model
    litellm_base_url: str | None = None  # For custom endpoints
    litellm_timeout: int = 600  # Timeout in seconds

    # Signal Configuration
    signal_phone_number: str | None = None  # Agent's registered phone number
    allowed_senders: list[str] = []  # Legacy allowlist for Signal; empty = deny all
    allowed_senders_by_channel: dict[str, list[str]] = Field(
        default_factory=dict
    )  # Prefer per-channel allowlists; empty/missing = deny all

    # Conversation Storage
    conversation_folder: str = "Brain/Conversations"  # Obsidian path for conversations
    summary_every_turns: int = 7  # Write a summary every N assistant turns (0 disables)

    # Code-Mode / UTCP
    utcp_config_path: str = "~/.config/brain/utcp.json"
    code_mode_timeout: int = 30

    @model_validator(mode="after")
    def populate_database_url(self) -> "Settings":
        if self.database_url:
            return self
        if not self.postgres_password:
            return self
        self.database_url = (
            f"postgresql://brain:{self.postgres_password}@postgres:5432/brain"
        )
        return self

    @model_validator(mode="after")
    def validate_sender_allowlist(self) -> "Settings":
        if self.allowed_senders_by_channel:
            return self
        if self.allowed_senders:
            return self
        raise ValueError(
            "ALLOWED_SENDERS or ALLOWED_SENDERS_BY_CHANNEL must be configured."
        )

# Global settings instance
settings = Settings()
