"""Trace 记录模型 — 每一次 LLM 调用的完整观测数据"""

from datetime import datetime, timezone
from sqlalchemy import String, Integer, Float, DateTime, Text, ForeignKey, Index, JSON
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


def _utcnow():
    return datetime.now(timezone.utc)


class TraceRecord(Base):
    __tablename__ = "trace_records"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: __import__("uuid").uuid4().hex
    )

    # ── 归属 ──
    api_key_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("api_keys.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # ── 模型信息 ──
    model: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(
        String(64), nullable=False, default="openai", comment="模型供应商"
    )

    # ── 请求 / 响应体（JSON 字段，PG 下自动升级为 JSONB）──
    request_body: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    response_body: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # ── Token 与成本 ──
    token_input: Mapped[int] = mapped_column(Integer, default=0)
    token_output: Mapped[int] = mapped_column(Integer, default=0)
    cost: Mapped[float] = mapped_column(Float, default=0.0)

    # ── 性能 ──
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)

    # ── 状态 ──
    status: Mapped[str] = mapped_column(
        String(32), default="success", comment="success | error"
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── 链路追踪（P2 启用）──
    trace_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )

    # ── 时间戳 ──
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, index=True
    )

    __table_args__ = (
        Index("idx_trace_key_time", "api_key_id", "created_at"),
        Index("idx_trace_trace_id", "trace_id"),
    )
