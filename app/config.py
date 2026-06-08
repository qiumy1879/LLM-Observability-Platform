"""应用配置 — 所有配置项统一从环境变量读取

数据库模式：
  - 设置 USE_SQLITE=true（默认）→ 使用 SQLite，无需 Docker
  - 设置 USE_SQLITE=false → 使用 PostgreSQL（需要 Docker）
"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── 数据库模式 ──
    use_sqlite: bool = True  # 默认 SQLite（本地开发），生产改为 false

    # ── PostgreSQL（Docker 启动后使用）──
    pg_host: str = "localhost"
    pg_port: int = 15432
    pg_user: str = "llmobs"
    pg_password: str = "llmobs_secret"
    pg_db: str = "llm_observability"

    # ── SQLite ──
    sqlite_path: str = "llm_observability.db"

    @property
    def database_url(self) -> str:
        if self.use_sqlite:
            return f"sqlite+aiosqlite:///{self.sqlite_path}"
        return (
            f"postgresql+asyncpg://{self.pg_user}:{self.pg_password}"
            f"@{self.pg_host}:{self.pg_port}/{self.pg_db}"
        )

    # ── 应用 ──
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    debug: bool = True

    # ── 异步写入 ──
    write_queue_size: int = 10000
    write_batch_size: int = 50
    write_flush_interval: int = 5
    stats_flush_interval: int = 10

    # ── 数据保留 ──
    trace_retention_days: int = 30

    # ── 请求体截断 ──
    max_body_chars: int = 10000

    # ── 默认 LLM 供应商 ──
    default_model: str = "claude-sonnet-4-6"
    default_provider: str = "anthropic"

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
