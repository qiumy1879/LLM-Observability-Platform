"""API Key 模型 — 多租户隔离的最小单元"""

import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Boolean, Integer, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


def _utcnow():
    """兼容 SQLite 和 PG 的当前时间函数"""
    return datetime.now(timezone.utc)


class ApiKey(Base):
    __tablename__ = "api_keys"

    # UUID 存为 String 以兼容 SQLite 和 PG
    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    key: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    rate_limit: Mapped[int] = mapped_column(
        Integer, default=60, comment="次/分钟，0 表示不限制"
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow
    )
