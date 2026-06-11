"""API Key 鉴权 + 限流

从 Authorization: Bearer <key> 中提取 Key，查库验证有效性，
将 api_key_id 注入 request.state 供后续使用。
同时基于内存滑动窗口执行简单的速率限制。

通过 FastAPI Depends 共享数据库会话，避免重复创建连接。
"""

import time
from collections import defaultdict
from fastapi import Request, HTTPException, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.models.api_key import ApiKey


def _rate_limiter(api_key_id: str, max_per_minute: int) -> bool:
    """简单的内存滑动窗口限流。

    返回 True 表示允许通过，False 表示被限制。
    """
    if max_per_minute <= 0:
        return True  # 0 = 不限制

    now = time.time()
    window = 60  # 1 分钟窗口
    key = f"rl_{api_key_id}"

    _rate_limiter._buckets.setdefault(key, [])
    bucket = _rate_limiter._buckets[key]

    # 清理过期时间戳
    cutoff = now - window
    bucket[:] = [t for t in bucket if t > cutoff]

    if len(bucket) >= max_per_minute:
        return False

    bucket.append(now)
    return True


_rate_limiter._buckets: dict[str, list[float]] = defaultdict(list)


async def verify_api_key(request: Request, db: AsyncSession = Depends(get_db)):
    """验证 API Key，执行限流，将 api_key_id 注入 request.state"""
    auth = request.headers.get("Authorization", "")
    if not auth.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")

    raw_key = auth[7:].strip()
    if not raw_key:
        raise HTTPException(status_code=401, detail="Empty API key")

    result = await db.execute(
        select(ApiKey).where(ApiKey.key == raw_key, ApiKey.is_active == True)
    )
    api_key = result.scalar_one_or_none()

    if api_key is None:
        raise HTTPException(status_code=401, detail="Invalid or inactive API key")

    # ── 限流检查 ──
    if not _rate_limiter(api_key.id, api_key.rate_limit):
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    request.state.api_key_id = api_key.id
    request.state.api_key_name = api_key.name
    request.state.rate_limit = api_key.rate_limit
