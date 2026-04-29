from decimal import Decimal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RAGP_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/ragp"
    secret_key: str = "change-me-in-production"
    debug: bool = False

    # Redis (used by ARQ worker queue and rate limiting)
    redis_host: str = "rag-p-redis-master"
    redis_port: int = 6379

    # Rate limiting (sliding window, 60-second window)
    rate_limit_per_key_rpm: int = 60
    rate_limit_per_org_rpm: int = 1000
    enforce_subscription_quotas: bool = True

    # Login brute-force protection (sliding window per IP+email)
    login_rate_limit_attempts: int = 5
    login_rate_limit_window_seconds: int = 900

    # Auth cookies. Keep false for local HTTP; enable in TLS deployments.
    session_cookie_secure: bool = False
    allow_legacy_org_header: bool = False

    # Permify
    permify_url: str = "http://localhost:3476"
    permify_tenant_id: str = "t1"

    # Langfuse
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"

    # LiteLLM default model
    default_llm_model: str = "deepseek/deepseek-v4-flash"
    default_embedding_model: str = "openai/text-embedding-3-small"
    llm_fallback_mode: str = "disabled"  # disabled | extractive

    # Billing — welcome bonus for new organizations (ENV: RAGP_STARTING_BALANCE_USD).
    # Default 0: every new account must top up via /pricing → ЮKassa to use anything.
    starting_balance_usd: Decimal = Decimal("0")

    # YooKassa payment gateway
    yookassa_shop_id: str = ""  # RAGP_YOOKASSA_SHOP_ID
    yookassa_secret_key: str = ""  # RAGP_YOOKASSA_SECRET_KEY
    yookassa_return_url: str = "https://lekottt.ru/account/billing"  # RAGP_YOOKASSA_RETURN_URL
    yookassa_webhook_secret: str = ""  # RAGP_YOOKASSA_WEBHOOK_SECRET
    yookassa_test_mode: bool = True  # RAGP_YOOKASSA_TEST_MODE
    yookassa_taxation_system: int = 6  # 6 = NPD (self-employed)
    yookassa_inn: str = ""  # RAGP_YOOKASSA_INN
    usd_to_rub_markup: Decimal = Decimal("0.03")  # 3% markup for exchange rate risk

    # S3-compatible object storage for raw uploaded documents.
    s3_endpoint_url: str = ""
    s3_region: str = ""
    s3_bucket: str = ""
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""


settings = Settings()
