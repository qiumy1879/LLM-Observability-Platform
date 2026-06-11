"""共享工具函数 — 跨模块复用的通用逻辑"""

from datetime import datetime, timezone


def utcnow() -> datetime:
    """返回带 UTC 时区的当前时间，兼容 SQLite 和 PostgreSQL"""
    return datetime.now(timezone.utc)
