"""LLM 模型适配器 — 统一不同供应商的调用接口

目前支持：
  - OpenAI 兼容格式（OpenAI / DeepSeek / 千问 等）
  - Anthropic（Claude）

扩展方式：新增一个 async def call_xxx() 并在 _adapters dict 中注册即可。
"""

import time
import httpx
from app.config import settings


class LLMAdapter:
    """统一入口：根据 provider 派发到对应的调用方法"""

    def __init__(self):
        self._client = None  # 延迟初始化，避免 import 时报 SSL 错误

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=120.0)
        return self._client

    async def call(
        self,
        provider: str,
        model: str,
        body: dict,
        api_key: str | None = None,
    ) -> dict:
        """调用 LLM，返回统一格式的观测数据"""
        start = time.perf_counter()

        if provider in ("openai", "deepseek", "qwen", "zhipu"):
            result = await self._call_openai_compatible(provider, model, body, api_key)
        elif provider == "anthropic":
            result = await self._call_anthropic(provider, model, body, api_key)
        else:
            result = await self._call_openai_compatible(provider, model, body, api_key)

        result["latency_ms"] = int((time.perf_counter() - start) * 1000)
        return result

    async def _call_openai_compatible(
        self, provider: str, model: str, body: dict, api_key: str | None
    ) -> dict:
        """OpenAI 兼容格式 — GPT / DeepSeek / 千问等"""
        base_urls = {
            "openai": "https://api.openai.com",
            "deepseek": "https://api.deepseek.com",
            "qwen": "https://dashscope.aliyuncs.com/compatible-mode",
            "zhipu": "https://open.bigmodel.cn/api/paas/v4",
        }
        base = base_urls.get(provider, f"https://api.{provider}.com")
        url = f"{base}/v1/chat/completions"

        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        # 替换 body 中的 model（用户可能指定了不同的模型名）
        body = {**body, "model": model}

        try:
            cl = await self._get_client()
            resp = await cl.post(url, json=body, headers=headers)
            resp_data = resp.json()

            if resp.status_code >= 400:
                return {
                    "status": "error",
                    "error_message": resp_data.get("error", {}).get("message", str(resp_data)),
                    "response_body": resp_data,
                    "model": model,
                    "provider": provider,
                    "token_input": 0,
                    "token_output": 0,
                    "cost": 0.0,
                }

            usage = resp_data.get("usage", {})
            return {
                "status": "success",
                "response_body": resp_data,
                "model": model,
                "provider": provider,
                "token_input": usage.get("prompt_tokens", 0),
                "token_output": usage.get("completion_tokens", 0),
                "cost": _estimate_cost(provider, model, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)),
            }
        except Exception as e:
            return {
                "status": "error",
                "error_message": str(e),
                "model": model,
                "provider": provider,
                "token_input": 0,
                "token_output": 0,
                "cost": 0.0,
            }

    async def _call_anthropic(
        self, provider: str, model: str, body: dict, api_key: str | None
    ) -> dict:
        """Anthropic Messages API → 内部转为类 OpenAI 格式"""
        url = "https://api.anthropic.com/v1/messages"

        # 将 OpenAI 格式的 messages 转为 Anthropic 格式
        messages = body.get("messages", [])
        system_msg = None
        anthropic_messages = []
        for m in messages:
            if m["role"] == "system":
                system_msg = m["content"]
            else:
                anthropic_messages.append({"role": m["role"], "content": m["content"]})

        req = {
            "model": model,
            "max_tokens": body.get("max_tokens", 4096),
            "messages": anthropic_messages,
        }
        if system_msg:
            req["system"] = system_msg

        headers = {
            "x-api-key": api_key or "",
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }

        try:
            cl = await self._get_client()
            resp = await cl.post(url, json=req, headers=headers)
            resp_data = resp.json()

            if resp.status_code >= 400:
                return {
                    "status": "error",
                    "error_message": resp_data.get("error", {}).get("message", str(resp_data)),
                    "response_body": resp_data,
                    "model": model,
                    "provider": provider,
                    "token_input": 0,
                    "token_output": 0,
                    "cost": 0.0,
                }

            usage = resp_data.get("usage", {})
            token_input = usage.get("input_tokens", 0)
            token_output = usage.get("output_tokens", 0)

            return {
                "status": "success",
                "response_body": resp_data,
                "model": model,
                "provider": provider,
                "token_input": token_input,
                "token_output": token_output,
                "cost": _estimate_cost(provider, model, token_input, token_output),
            }
        except Exception as e:
            return {
                "status": "error",
                "error_message": str(e),
                "model": model,
                "provider": provider,
                "token_input": 0,
                "token_output": 0,
                "cost": 0.0,
            }

    async def close(self):
        if self._client is not None:
            await self._client.aclose()


# ── 价格估算（$/token，以官方最新定价为准，面试时可说明这是可配置的）──

_PRICES: dict[str, dict[str, tuple[float, float]]] = {
    # (输入价格, 输出价格) 单位：$/token
    "openai": {
        "gpt-4o": (0.0000025, 0.000010),
        "gpt-4o-mini": (0.00000015, 0.0000006),
        "gpt-4-turbo": (0.000010, 0.000030),
    },
    "deepseek": {
        "deepseek-chat": (0.00000014, 0.00000028),
        "deepseek-reasoner": (0.00000055, 0.00000219),
    },
    "anthropic": {
        "claude-sonnet-4-6": (0.000003, 0.000015),
        "claude-opus-4-8": (0.000015, 0.000075),
        "claude-haiku-4-5": (0.0000008, 0.000004),
    },
}

_DEFAULT_PRICE = (0.000001, 0.000005)  # 未知模型默认价格


def _estimate_cost(provider: str, model: str, input_tokens: int, output_tokens: int) -> float:
    """根据模型定价估算本次调用费用"""
    prices = _PRICES.get(provider, {}).get(model, _DEFAULT_PRICE)
    cost = input_tokens * prices[0] + output_tokens * prices[1]
    return round(cost, 8)


# ── 全局单例 ──
adapter = LLMAdapter()
