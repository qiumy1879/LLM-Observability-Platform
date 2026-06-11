"""FastAPI 入口"""

import asyncio
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from app.config import settings
from app.core.database import init_db
from app.services.write_worker import start_worker, stop_worker, stats_cache
from app.api import proxy, keys, dashboard


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── 启动 ──
    await init_db()
    asyncio.create_task(start_worker())
    yield
    # ── 关闭 ──
    await stop_worker()


app = FastAPI(
    title="LLM Observability Platform",
    description="LLM 调用可观测性平台 — 代理模式 + 全量追踪 + 成本分析",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,  # Bearer Token 鉴权，不需要 Cookie
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"status": "healthy", "version": "0.1.0"}


@app.get("/")
async def dashboard_page():
    static_dir = os.path.join(os.path.dirname(__file__), "static")
    return FileResponse(os.path.join(static_dir, "dashboard.html"))


# ── 注册路由 ──
app.include_router(proxy.router, tags=["Proxy"])
app.include_router(keys.router, prefix="/api", tags=["API Keys"])
app.include_router(dashboard.router, prefix="/api", tags=["Dashboard"])
