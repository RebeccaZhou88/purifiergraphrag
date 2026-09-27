# @Author: RebeccaZhou
# @Description: Plugin 4: LLM answer generation, streams a natural-language answer from graph context / Plugin 4: LLM
#              答案生成。基于图上下文用 LLM 生成自然语言回答（流式）。
"""

Plugin 4: LLM 答案生成。基于图上下文用 LLM 生成自然语言回答（流式）。
"""
from __future__ import annotations

from typing import Any, AsyncIterator

from semantic_kernel.functions import KernelArguments, kernel_function

from app.core.logging import StepEventBus
from app.llm.prompts import ANSWER_GENERATION_SYSTEM, answer_generation_user
from app.llm.providers import LLMProvider


class LLMGenerationPlugin:
    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    @kernel_function(name="generate_stream", description="流式生成自然语言回答")
    async def generate_stream(
        self,
        question: str,
        context: dict[str, Any],
        arguments: KernelArguments,
    ) -> AsyncIterator[str]:
        bus: StepEventBus = arguments["bus"]
        await bus.emit("llm_generation", "开始流式生成回答", {})
        user = answer_generation_user(
            question,
            context.get("cypher", ""),
            context.get("context_json", ""),
        )
        emitted: list[str] = []
        try:
            # 注意：不传 max_tokens —— deepseek-v4-flash / qwen3 等混合推理模型的
            # 思考 token 会计入 max_tokens 预算，200 会被思考耗尽导致正文为空。
            # 长度由 ANSWER_GENERATION_SYSTEM 的"100 字以内"约束。
            async for token in self._llm.stream_chat(ANSWER_GENERATION_SYSTEM, user):
                emitted.append(token)
                yield token
        except Exception as e:
            await bus.emit("llm_generation", f"流式生成异常: {e}", {})
        if not emitted:
            # 流式零输出（异常或空流）→ 非流式兜底，保证有答案
            await bus.emit("llm_generation", "流式无输出，改用非流式生成", {})
            text = await self._llm.chat(ANSWER_GENERATION_SYSTEM, user, temperature=0.2)
            if text:
                yield text
        await bus.emit("llm_generation", "生成完成", {})
