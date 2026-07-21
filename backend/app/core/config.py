from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"
    chroma_persist_dir: str = "./chroma_data"
    log_level: str = "INFO"
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_url: str = ""  # full rediss://… URL (Upstash/managed); overrides host/port
    frontend_origin: str = "http://localhost:3000"
    analyze_enabled: bool = True
    spend_ceiling_usd: float = 50.0
    trial_refresh_enabled: bool = False  # daily CT.gov freshness refresh (off in dev/CI)

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()
