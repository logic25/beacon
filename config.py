"""
Configuration management using Pydantic Settings.
Validates environment variables and provides type-safe configuration.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Anthropic / Claude Settings
    anthropic_api_key: str = Field(..., description="Anthropic API key for Claude")
    claude_model: str = Field(
        default="claude-haiku-4-5-20251001",
        description="Claude model to use (haiku or sonnet)",
    )
    claude_max_tokens: int = Field(default=1500, ge=100, le=4096)
    claude_temperature: float = Field(default=0.3, ge=0.0, le=1.0)

    # Google Chat Settings
    google_service_account_file: str = Field(
        default="google-chat-bot-key.json",
        description="Path to Google service account JSON file",
    )

    # Session Settings
    session_file: str = Field(default="user_sessions.json")
    max_history_length: int = Field(default=10, ge=1, le=50)
    session_ttl_hours: int = Field(default=24, ge=1)

    # Server Settings
    port: int = Field(default=8080, ge=1024, le=65535)
    debug: bool = Field(default=False)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(default="INFO")

    # RAG Settings
    rag_enabled: bool = Field(default=True, description="Enable RAG retrieval")
    rag_top_k: int = Field(default=5, ge=1, le=20)
    rag_min_score: float = Field(default=0.5, ge=0.0, le=1.0)

    # Pinecone Settings
    pinecone_api_key: str = Field(default="", description="Pinecone API key")
    pinecone_index_name: str = Field(default="greenlight-docs")

    # Embedding Settings
    embedding_provider: Literal["voyage", "openai"] = Field(default="voyage")
    embedding_dimension: int = Field(default=1024)  # Voyage default

    # Voyage AI Settings (recommended for Claude)
    voyage_api_key: str = Field(default="", description="Voyage AI API key")
    voyage_model: str = Field(default="voyage-2")

    # OpenAI Settings (alternative for embeddings)
    openai_api_key: str = Field(default="", description="OpenAI API key for embeddings")
    openai_embedding_model: str = Field(default="text-embedding-3-small")

    @field_validator("claude_model")
    @classmethod
    def validate_model(cls, v: str) -> str:
        """Validate and normalize Claude model name."""
        valid_models = {
            "haiku": "claude-haiku-4-5-20251001",
            "claude-haiku-4-5-20251001": "claude-haiku-4-5-20251001",
            "sonnet": "claude-sonnet-4-5-20250929",
            "claude-sonnet-4-5-20250929": "claude-sonnet-4-5-20250929",
        }
        normalized = v.lower().strip()
        if normalized in valid_models:
            return valid_models[normalized]
        raise ValueError(
            f"Invalid model: {v}. Use 'haiku', 'sonnet', or full model names."
        )


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
