# @Author: RebeccaZhou
# @Description: LLM provider adapters: Qwen / DeepSeek / Azure OpenAI behind a unified OpenAI-compatible interface
#              LLM 提供方适配：Qwen / Deepseek / Azure OpenAI，统一 OpenAI 兼容接口。
"""

通过 Azure AI Foundry 部署，三类模型均暴露 OpenAI 兼容的 chat/completions。
无 API key 时退回 stub，保证开发环境可联调。
"""
from __future__ import annotations

import json
from typing import AsyncIterator

from loguru import logger

from app.core.config import settings

class LLMProvider:
    """统一 LLM 接口：chat / stream_chat。"""

    def __init__(self, provider: str | None = None) -> None:
        self.provider = provider or settings.llm_provider
        self._client = None
        self._stub_mode = False
        self._extra_body: dict = {}
        # 评估用：跨多次 chat/stream_chat 累加 token 用量（评估为串行调用）。
        self.usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        self._init()

    def reset_usage(self) -> None:
        """每条评估用例开始前清零 token 累加器。"""
        self.usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    def _add_usage(self, u: object) -> None:
        """把一次响应的 usage 累加进 self.usage（兼容不同网关的字段缺失）。"""
        if u is None:
            return
        p = getattr(u, "prompt_tokens", None) or 0
        c = getattr(u, "completion_tokens", None) or 0
        t = getattr(u, "total_tokens", None) or (p + c)
        self.usage["prompt_tokens"] += p
        self.usage["completion_tokens"] += c
        self.usage["total_tokens"] += t

    def _provider_config(self) -> tuple[str, str, str]:
        """按 self.provider 取对应的 (endpoint, api_key, model)。"""
        p = self.provider
        if p == "qwen":
            return settings.qwen_endpoint, settings.qwen_api_key, settings.qwen_model
        if p == "deepseek":
            return settings.deepseek_endpoint, settings.deepseek_api_key, settings.deepseek_model
        if p == "azure_openai":
            return (
                settings.azure_openai_endpoint,
                settings.azure_openai_api_key,
                settings.azure_openai_deployment,
            )
        # 未知 provider 退回默认
        return settings.llm_endpoint(), settings.llm_api_key(), settings.llm_model()

    def _init(self) -> None:
        endpoint, api_key, model = self._provider_config()
        self._model = model
        if not api_key or not endpoint:
            logger.warning(
                f"LLM provider={self.provider} 缺少 endpoint/api_key，启用 stub 模式（本地回环假数据）。"
            )
            self._stub_mode = True
            return
        try:
            # Azure OpenAI 需用 AzureOpenAI 客户端处理 api-version 与 deployment 路径
            if self.provider == "azure_openai":
                from openai import AsyncAzureOpenAI

                self._client = AsyncAzureOpenAI(
                    api_key=api_key,
                    azure_endpoint=endpoint.rstrip("/"),
                    azure_deployment=model,
                    api_version="2024-02-15-preview",
                )
            else:
                from openai import AsyncOpenAI

                # DashScope / DeepSeek / Foundry 网关均使用 OpenAI 兼容协议
                base_url = endpoint.rstrip("/")
                if not base_url.endswith("/v1"):
                    base_url = f"{base_url}/v1"
                self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)
                # 混合推理模型关闭内部思考：省 1~2s 延迟，且避免思考 token 吃掉
                # max_tokens 预算导致正文为空/截断
                if self.provider == "deepseek":
                    self._extra_body = {"thinking": {"type": "disabled"}}
                elif self.provider == "qwen":
                    self._extra_body = {"enable_thinking": False}
        except Exception as e:
            logger.warning(f"初始化 OpenAI 客户端失败，启用 stub: {e}")
            self._stub_mode = True

    @property
    def model_name(self) -> str:
        return self._model

    def _effective_temperature(self, temperature: float) -> float | None:
        """部分 Azure 模型（如 gpt-5-nano）不支持自定义 temperature，仅接受默认值。"""
        if self.provider == "azure_openai":
            return None
        return temperature

    async def chat(self, system: str, user: str, temperature: float = 0.2) -> str:
        """单轮问答，返回完整文本。"""
        if self._stub_mode:
            return self._stub_response(system, user)
        kwargs = dict(
            model=self.model_name,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        t = self._effective_temperature(temperature)
        if t is not None:
            kwargs["temperature"] = t
        if self._extra_body:
            kwargs["extra_body"] = self._extra_body
        resp = await self._client.chat.completions.create(**kwargs)
        self._add_usage(getattr(resp, "usage", None))
        return resp.choices[0].message.content or ""

    async def stream_chat(
        self,
        system: str,
        user: str,
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        """流式问答，逐 token 返回。"""
        if self._stub_mode:
            text = self._stub_response(system, user)
            for ch in text:
                yield ch
            return
        kwargs = dict(
            model=self.model_name,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            stream=True,
        )
        t = self._effective_temperature(temperature)
        if t is not None:
            kwargs["temperature"] = t
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if self._extra_body:
            kwargs["extra_body"] = self._extra_body
        # 让最后一个 chunk 携带 usage（token 用量统计用；OpenAI/Azure/DashScope 均兼容）
        kwargs["stream_options"] = {"include_usage": True}
        stream = await self._client.chat.completions.create(**kwargs)
        async for chunk in stream:
            self._add_usage(getattr(chunk, "usage", None))
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            content = getattr(delta, "content", None) if delta is not None else None
            if content:
                yield content

    def _stub_response(self, system: str, user: str) -> str:
        """本地无 key 时的回环假数据，便于前端联调。"""
        if "实体抽取器" in system:
            return json.dumps(
                {
                    "intent": "filter_compatibility",
                    "entities": {"model": "PG-A100"},
                    "scenario": "filter_compatibility",
                },
                ensure_ascii=False,
            )
        if "Cypher 生成器" in system:
            return "MATCH (m:Model {name: 'PG-A100'})-[:USES]->(f:Filter) RETURN f.code, f.type"
        # 默认：答案生成
        return (
            "（stub 模式）根据图谱，PG-A100 使用 PP棉前置(FC-PP01)、活性炭(FC-CTO02)、"
            "RO反渗透膜(FC-RO03)、后置活性炭(FC-Post04) 四支滤芯。"
        )

_provider_cache: dict[str, LLMProvider] = {}

def get_provider(provider: str | None = None) -> LLMProvider:
    key = provider or settings.llm_provider
    if key not in _provider_cache:
        _provider_cache[key] = LLMProvider(key)
    return _provider_cache[key]
