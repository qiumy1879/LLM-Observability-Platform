"""API Key 鉴权中间件

从 Authorization: Bearer <key> 中提取 Key，查库验证有效性，
将 api_key_id 注入 request.state 供后续使用。
"""

from fastapi import Request, HTTPException
from sqlalchemy import select
from app.core.database import async_session
from app.models.api_key import ApiKey


async def verify_api_key(request: Request):
    """验证 API Key 并注入 api_key_id 到 request.state"""
    auth = request.headers.get("Authorization", "")
    if not auth.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")

    raw_key = auth[7:].strip()
    if not raw_key:
        raise HTTPException(status_code=401, detail="Empty API key")

    async with async_session() as session:
        result = await session.execute(
            select(ApiKey).where(ApiKey.key == raw_key, ApiKey.is_active == True)
        )
        api_key = result.scalar_one_or_none()

        if api_key is None:
            raise HTTPException(status_code=401, detail="Invalid or inactive API key")

        request.state.api_key_id = api_key.id
        request.state.api_key_name = api_key.name
        request.state.rate_limit = api_key.rate_limit
