"""核心代理端点 — 接收用户请求，转发到真实模型，异步记录观测数据

流程：
  1. 鉴权（API Key 中间件）
  2. 接收 OpenAI 格式请求体
  3. 转发给真实模型（主链路）
  4. 响应立即返回给用户
  5. 后台异步写入 trace_records + 更新内存计数器
"""

import json
import os
from fastapi import APIRouter, Request, Depends
from fastapi.responses import JSONResponse
from app.middleware.api_key_auth import verify_api_key
from app.services.llm_adapter import adapter
from app.services.write_worker import write_queue, stats_cache
from app.config import settings

router = APIRouter()


def _truncate_body(body: dict | None, max_chars: int = None) -> dict | None:
    """截断请求/响应体，防止存储膨胀"""
    if body is None:
        return None
    max_chars = max_chars or settings.max_body_chars
    raw = json.dumps(body, ensure_ascii=False, default=str)
    if len(raw) > max_chars:
        return {"truncated": True, "preview": raw[:max_chars], "original_length": len(raw)}
    return body


@router.post("/v1/chat/completions")
async def proxy_chat_completions(request: Request, _=Depends(verify_api_key)):
    """OpenAI 兼容的 Chat Completions 代理端点"""
    body = await request.json()

    # ── 确定模型和供应商 ──
    raw_model = body.get("model", settings.default_model)
    if "/" in raw_model:
        provider, model = raw_model.split("/", 1)
    else:
        provider = settings.default_provider
        model = raw_model

    # ── 获取用户的真实 LLM API Key ──
    user_llm_key = os.getenv(f"LLM_KEY_{provider.upper()}")

    # ── 调用真实模型（主链路）──
    result = await adapter.call(
        provider=provider,
        model=model,
        body=body,
        api_key=user_llm_key,
    )

    # ── 异步记录观测数据（不阻塞主链路）──
    trace_payload = {
        "api_key_id": request.state.api_key_id,
        "model": model,
        "provider": provider,
        "request_body": _truncate_body(body),
        "response_body": _truncate_body(result.get("response_body")),
        "token_input": result.get("token_input", 0),
        "token_output": result.get("token_output", 0),
        "cost": result.get("cost", 0.0),
        "latency_ms": result.get("latency_ms", 0),
        "status": result.get("status", "error"),
        "error_message": result.get("error_message"),
        "trace_id": request.headers.get("X-Trace-Id"),
    }
    await write_queue.put(trace_payload)

    # ── 更新内存计数器 ──
    stats_cache.record(
        api_key_id=request.state.api_key_id,
        model=model,
        cost=result.get("cost", 0.0),
        tokens=result.get("token_input", 0) + result.get("token_output", 0),
        is_error=(result.get("status") != "success"),
    )

    # ── 返回（OpenAI 兼容格式）──
    if result.get("status") == "error":
        return JSONResponse(
            status_code=502,
            content={
                "error": {
                    "message": result.get("error_message", "Upstream error"),
                    "type": "proxy_error",
                }
            },
        )

    return result.get("response_body", {})
