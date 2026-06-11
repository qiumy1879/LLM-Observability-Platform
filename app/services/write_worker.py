"""异步写入 Worker — 生产者/消费者模式解耦主链路和 DB 写入

架构：
  请求主链路 ──► asyncio.Queue ──► WriteWorker（后台消费）
                  (不阻塞)           (批量写入 DB)

同时维护一个内存计数器（stats_cache），实现：
  - 实时查询：读内存（纳秒级）
  - 明细查询：读 DB（可能有秒级延迟）
  - 启动恢复：从 DB 恢复当日计数
  - 关闭刷盘：存档当日快照
"""

import asyncio
import time
from datetime import datetime, timezone, timedelta
from typing import Optional
from sqlalchemy import select, func
from app.config import settings
from app.core.database import async_session
from app.models.trace_record import TraceRecord

# ── 内存队列 ──
write_queue: asyncio.Queue = asyncio.Queue(maxsize=settings.write_queue_size)

# ── Worker 控制 ──
_worker_task: Optional[asyncio.Task] = None
_shutdown_flag = False


# ═══════════════════════════════════════════════════════════
# 内存计数器（实时查询热点数据）
# ═══════════════════════════════════════════════════════════

class StatsCache:
    """内存计数器，用 asyncio.Lock 保证并发安全"""

    def __init__(self):
        self._data: dict = {}
        self._lock = asyncio.Lock()

    async def record(self, api_key_id: str, model: str, cost: float, tokens: int, is_error: bool):
        async with self._lock:
            entry = self._data.setdefault(api_key_id, {"calls": 0, "cost": 0.0, "tokens": 0, "errors": 0, "by_model": {}})
            entry["calls"] += 1
            entry["cost"] += cost
            entry["tokens"] += tokens
            if is_error:
                entry["errors"] += 1

            model_entry = entry["by_model"].setdefault(model, {"calls": 0, "cost": 0.0, "tokens": 0})
            model_entry["calls"] += 1
            model_entry["cost"] += cost
            model_entry["tokens"] += tokens

    async def get_summary(self, api_key_id: Optional[str] = None) -> dict:
        async with self._lock:
            if api_key_id:
                return self._data.get(api_key_id, {"calls": 0, "cost": 0.0, "tokens": 0, "errors": 0, "by_model": {}})

            total = {"calls": 0, "cost": 0.0, "tokens": 0, "errors": 0, "by_model": {}}
            for entry in self._data.values():
                total["calls"] += entry["calls"]
                total["cost"] += entry["cost"]
                total["tokens"] += entry["tokens"]
                total["errors"] += entry["errors"]
                for model, m in entry["by_model"].items():
                    mt = total["by_model"].setdefault(model, {"calls": 0, "cost": 0.0, "tokens": 0})
                    mt["calls"] += m["calls"]
                    mt["cost"] += m["cost"]
                    mt["tokens"] += m["tokens"]
            return total

    async def restore_from_db(self):
        """启动时从 DB 恢复今日计数，防止重启后清零"""
        async with async_session() as session:
            today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
            result = await session.execute(
                select(
                    TraceRecord.api_key_id,
                    TraceRecord.model,
                    func.count(TraceRecord.id).label("calls"),
                    func.coalesce(func.sum(TraceRecord.cost), 0).label("cost"),
                    func.coalesce(func.sum(TraceRecord.token_input + TraceRecord.token_output), 0).label("tokens"),
                    func.count(TraceRecord.id).filter(TraceRecord.status != "success").label("errors"),
                )
                .where(TraceRecord.created_at >= today_start)
                .group_by(TraceRecord.api_key_id, TraceRecord.model)
            )
            rows = result.all()
            async with self._lock:
                for row in rows:
                    key_id = row.api_key_id or "unknown"
                    entry = self._data.setdefault(key_id, {"calls": 0, "cost": 0.0, "tokens": 0, "errors": 0, "by_model": {}})
                    entry["calls"] += row.calls
                    entry["cost"] += float(row.cost)
                    entry["tokens"] += row.tokens
                    entry["errors"] += row.errors
                    entry["by_model"][row.model] = {
                        "calls": row.calls,
                        "cost": float(row.cost),
                        "tokens": row.tokens,
                    }

    async def flush_to_db(self):
        """关闭时把快照写回 DB（标记为今日聚合）"""
        # 当前实现：计数器数据已在 trace_records 明细表中，无需额外存档。
        # 未来可加一张 daily_stats 表存每日聚合数据。
        pass


stats_cache = StatsCache()


# ═══════════════════════════════════════════════════════════
# 写入 Worker
# ═══════════════════════════════════════════════════════════

async def _batch_insert(records: list[dict]):
    """批量 INSERT trace_records（ORM 方式，兼容 SQLite 和 PG）"""
    if not records:
        return
    async with async_session() as session:
        for rec in records:
            trace = TraceRecord(
                api_key_id=rec.get("api_key_id"),
                model=rec.get("model", ""),
                provider=rec.get("provider", "openai"),
                request_body=rec.get("request_body"),
                response_body=rec.get("response_body"),
                token_input=rec.get("token_input", 0),
                token_output=rec.get("token_output", 0),
                cost=rec.get("cost", 0.0),
                latency_ms=rec.get("latency_ms", 0),
                status=rec.get("status", "success"),
                error_message=rec.get("error_message"),
                trace_id=rec.get("trace_id"),
            )
            session.add(trace)
        await session.commit()


async def _worker_loop():
    """后台 Worker：从队列取数据，攒够一批就写入 DB"""
    batch = []
    last_flush = time.time()

    while not _shutdown_flag:
        try:
            record = await asyncio.wait_for(write_queue.get(), timeout=1.0)
            batch.append(record)
        except asyncio.TimeoutError:
            pass

        now = time.time()
        if len(batch) >= settings.write_batch_size or (
            batch and (now - last_flush) >= settings.write_flush_interval
        ):
            await _batch_insert(batch)
            batch.clear()
            last_flush = now

    if batch:
        await _batch_insert(batch)


async def start_worker():
    global _worker_task
    # 启动时先从 DB 恢复今日计数
    await stats_cache.restore_from_db()
    _worker_task = asyncio.create_task(_worker_loop())


async def stop_worker():
    global _shutdown_flag
    _shutdown_flag = True
    if _worker_task:
        await _worker_task
    await stats_cache.flush_to_db()
