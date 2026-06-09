"""FastAPI 入口 """

import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.core.database import init_db
from app.services.write_worker import start_worker, stop_worker, stats_cache


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── 启动 ──
    await init_db()
    asyncio.create_task(start_worker())
    print(f"[启动] 数据库已初始化，Worker 已启动")
    yield
    # ── 关闭 ──
    await stop_worker()
    stats_cache.flush_to_db()  # 停机前最后刷一次


app = FastAPI(
    title="LLM Observability Platform",
    description="LLM 调用可观测性平台 — 代理模式 + 全量追踪 + 成本分析",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"status": "healthy", "version": "0.1.0"}


@app.get("/")
async def dashboard_page():
    from fastapi.responses import FileResponse
    import os
    static_dir = os.path.join(os.path.dirname(__file__), "static")
    return FileResponse(os.path.join(static_dir, "dashboard.html"))


# ── 注册路由（延迟导入避免循环依赖）──
from app.api import proxy, keys, dashboard  # noqa: E402

app.include_router(proxy.router, tags=["Proxy"])
app.include_router(keys.router, prefix="/api", tags=["API Keys"])
app.include_router(dashboard.router, prefix="/api", tags=["Dashboard"])
