"""Dashboard 数据接口 — 实时概览 + 按模型拆分 + 明细查询"""

from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Query, Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.models.trace_record import TraceRecord
from app.schemas.trace import (
    DashboardSummary,
    CostByModel,
    TraceResponse,
    TraceDetailResponse,
)
from app.services.write_worker import stats_cache

router = APIRouter()


@router.get("/dashboard/summary", response_model=DashboardSummary)
async def get_summary(db: AsyncSession = Depends(get_db)):
    """总览：今日实时统计数据"""
    realtime = await stats_cache.get_summary()

    from app.models.api_key import ApiKey
    key_result = await db.execute(
        select(func.count(ApiKey.id)).where(ApiKey.is_active == True)
    )
    active_keys = key_result.scalar() or 0

    by_model = [
        CostByModel(
            model=model,
            calls=data["calls"],
            total_cost=data["cost"],
            total_tokens=data["tokens"],
        )
        for model, data in realtime.get("by_model", {}).items()
    ]

    total_calls = realtime["calls"]
    total_errors = realtime["errors"]

    return DashboardSummary(
        total_calls_today=total_calls,
        total_cost_today=round(realtime["cost"], 6),
        total_tokens_today=realtime["tokens"],
        error_rate_today=round(total_errors / max(total_calls, 1), 4),
        active_keys=active_keys,
        by_model=by_model,
    )


@router.get("/dashboard/cost-by-model", response_model=list[CostByModel])
async def cost_by_model(
    days: int = Query(7, ge=1, le=90),
    db: AsyncSession = Depends(get_db),
):
    """按模型拆分成本（从 DB 查历史数据）"""
    cutoff = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days)

    result = await db.execute(
        select(
            TraceRecord.model,
            func.count(TraceRecord.id).label("calls"),
            func.coalesce(func.sum(TraceRecord.cost), 0).label("total_cost"),
            func.coalesce(
                func.sum(TraceRecord.token_input + TraceRecord.token_output), 0
            ).label("total_tokens"),
        )
        .where(TraceRecord.created_at >= cutoff)
        .group_by(TraceRecord.model)
        .order_by(func.sum(TraceRecord.cost).desc())
    )
    rows = result.all()

    return [
        CostByModel(
            model=row.model,
            calls=row.calls,
            total_cost=round(float(row.total_cost), 6),
            total_tokens=row.total_tokens,
        )
        for row in rows
    ]


@router.get("/traces", response_model=list[TraceResponse])
async def list_traces(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    api_key_id: str | None = None,
    model: str | None = None,
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """查询调用明细列表"""
    query = select(TraceRecord).order_by(TraceRecord.created_at.desc())

    if api_key_id:
        query = query.where(TraceRecord.api_key_id == api_key_id)
    if model:
        query = query.where(TraceRecord.model == model)
    if status:
        query = query.where(TraceRecord.status == status)

    query = query.offset(skip).limit(limit)
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/traces/{trace_id}", response_model=TraceDetailResponse)
async def get_trace_detail(trace_id: str, db: AsyncSession = Depends(get_db)):
    """查询单条调用详情（含 request/response body）"""
    result = await db.execute(
        select(TraceRecord).where(TraceRecord.id == trace_id)
    )
    trace = result.scalar_one_or_none()
    if trace is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Trace not found")
    return trace
