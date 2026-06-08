"""Trace / Dashboard 相关的 Pydantic 模型"""

from datetime import datetime
from pydantic import BaseModel, Field


class TraceResponse(BaseModel):
    id: str
    model: str
    provider: str
    token_input: int
    token_output: int
    cost: float
    latency_ms: int
    status: str
    error_message: str | None = None
    trace_id: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class TraceDetailResponse(TraceResponse):
    """单条详情 — 额外暴露 request / response body"""
    api_key_id: str | None = None
    request_body: dict | None = None
    response_body: dict | None = None


class TraceListParams(BaseModel):
    skip: int = Field(0, ge=0)
    limit: int = Field(50, ge=1, le=200)
    api_key_id: str | None = None
    model: str | None = None
    status: str | None = None


class CostByModel(BaseModel):
    model: str
    calls: int
    total_cost: float
    total_tokens: int


class DashboardSummary(BaseModel):
    total_calls_today: int
    total_cost_today: float
    total_tokens_today: int
    error_rate_today: float
    active_keys: int
    by_model: list[CostByModel]
