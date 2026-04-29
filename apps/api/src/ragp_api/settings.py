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

    # YooKassa webhook security (IP allowlist + server-side re-validation).
    # YooKassa does not sign webhooks, so we filter inbound traffic by source IP
    # against the published CIDRs and re-fetch the payment via /payments/{id}
    # to ensure the payload was not forged.
    yookassa_allowed_ips: str = (
        "185.71.76.0/27,185.71.77.0/27,77.75.153.0/25,77.75.154.128/25,"
        "77.75.156.11/32,77.75.156.35/32,2a02:5180::/32"
    )
    # CIDRs of trusted reverse proxies (Caddy/Docker bridge). Only X-Forwarded-For
    # entries originating from these are trusted; everything else falls back to
    # request.client.host to defeat XFF spoofing.
    yookassa_trusted_proxies: str = "127.0.0.1/32,172.16.0.0/12,10.0.0.0/8"
    yookassa_require_ip_check: bool = True
    yookassa_revalidate_payment: bool = True
    yookassa_revalidate_timeout_seconds: float = 10.0

    # Local BGE reranker (fallback for Cohere when its API is unreachable).
    bge_reranker_model: str = "BAAI/bge-reranker-v2-m3"
    bge_reranker_device: str = "cpu"
    bge_reranker_max_batch: int = 32

    # Experiment watchdog (background cron in workers/main.py).  An experiment
    # whose updated_at is older than this many seconds and is still in
    # queued/running is considered abandoned and force-failed.
    experiment_stale_timeout_seconds: int = 900
    experiment_watchdog_interval_minutes: int = 2

    # Cohere selective VPN routing (AmneziaWG sidecar).
    # Empty (default) -> direct connect; from RU IPs api.cohere.com / api.cohere.ai may be blocked.
    # Production value: http://cohere-egress:8888 — HTTP forward proxy in the sidecar.
    cohere_http_proxy: str = ""

    # S3-compatible object storage for raw uploaded documents.
    s3_endpoint_url: str = ""
    s3_region: str = ""
    s3_bucket: str = ""
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""


settings = Settings()
