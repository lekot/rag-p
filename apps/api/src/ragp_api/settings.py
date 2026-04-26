from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RAGP_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/ragp"
    secret_key: str = "change-me-in-production"
    debug: bool = False

    # Permify
    permify_url: str = "http://localhost:3476"
    permify_tenant_id: str = "t1"

    # Langfuse
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"

    # LiteLLM default model
    default_llm_model: str = "openai/gpt-4o-mini"
    default_embedding_model: str = "openai/text-embedding-3-small"


settings = Settings()
