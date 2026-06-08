"""API Key 管理 CRUD"""

import secrets
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.models.api_key import ApiKey
from app.schemas.api_key import ApiKeyCreate, ApiKeyResponse, ApiKeyListItem

router = APIRouter()


def _generate_key() -> str:
    return "sk-" + secrets.token_urlsafe(32)


@router.post("/keys", response_model=ApiKeyResponse, status_code=201)
async def create_key(payload: ApiKeyCreate, db: AsyncSession = Depends(get_db)):
    """创建新的 API Key"""
    key = ApiKey(
        key=_generate_key(),
        name=payload.name,
        rate_limit=payload.rate_limit,
    )
    db.add(key)
    await db.flush()
    await db.refresh(key)
    return key


@router.get("/keys", response_model=list[ApiKeyListItem])
async def list_keys(db: AsyncSession = Depends(get_db)):
    """列出所有 API Key"""
    result = await db.execute(select(ApiKey).order_by(ApiKey.created_at.desc()))
    return result.scalars().all()


@router.patch("/keys/{key_id}", response_model=ApiKeyResponse)
async def toggle_key(key_id: str, is_active: bool = None, db: AsyncSession = Depends(get_db)):
    """启用/禁用 API Key"""
    result = await db.execute(select(ApiKey).where(ApiKey.id == key_id))
    key = result.scalar_one_or_none()
    if key is None:
        raise HTTPException(status_code=404, detail="Key not found")

    if is_active is not None:
        key.is_active = is_active

    await db.flush()
    await db.refresh(key)
    return key


@router.delete("/keys/{key_id}", status_code=204)
async def delete_key(key_id: str, db: AsyncSession = Depends(get_db)):
    """删除 API Key"""
    result = await db.execute(select(ApiKey).where(ApiKey.id == key_id))
    key = result.scalar_one_or_none()
    if key is None:
        raise HTTPException(status_code=404, detail="Key not found")

    await db.delete(key)
    await db.flush()
