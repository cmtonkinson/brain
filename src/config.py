"""Configuration management for Brain assistant."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # LLM Configuration
    anthropic_api_key: str
    
    # Obsidian Configuration
    obsidian_api_key: str
    obsidian_url: str = "http://host.docker.internal:27123"
    obsidian_vault_path: str
    
    # Database Configuration
    database_url: str
    postgres_password: str
    
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

# Global settings instance
settings = Settings()
