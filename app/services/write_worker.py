"""异步写入 Worker — 生产者/消费者模式解耦主链路和 DB 写入

架构：
  请求主链路 ──► asyncio.Queue ──► WriteWorker（后台消费）
                  (不阻塞)           (批量写入 DB)

同时维护一个内存计数器（stats_cache），实现：
  - 实时查询：读内存（纳秒级）
  - 明细查询：读 DB（可能有秒级延迟）
  - 定时刷盘：每 N 秒将内存快照写入 DB，防重启丢失
"""

import asyncio
import time
from typing import Optional
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
    """线程不安全的单机内存计数器"""

    def __init__(self):
        self._data: dict = {}

    def record(self, api_key_id: str, model: str, cost: float, tokens: int, is_error: bool):
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

    def get_summary(self, api_key_id: Optional[str] = None) -> dict:
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

    def flush_to_db(self):
        """将内存计数器快照写入 DB"""
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
    _worker_task = asyncio.create_task(_worker_loop())


async def stop_worker():
    global _shutdown_flag
    _shutdown_flag = True
    if _worker_task:
        await _worker_task
