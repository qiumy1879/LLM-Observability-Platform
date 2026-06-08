"""API Key 相关的 Pydantic 模型"""

from datetime import datetime
from pydantic import BaseModel, Field


class ApiKeyCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128, description="Key 的备注名称")
    rate_limit: int = Field(60, ge=0, description="速率限制：次/分钟，0=不限制")


class ApiKeyResponse(BaseModel):
    id: str
    key: str
    name: str
    rate_limit: int
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class ApiKeyListItem(BaseModel):
    id: str
    name: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}
