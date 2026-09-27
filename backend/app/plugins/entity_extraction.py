# @Author: RebeccaZhou
# @Description: Plugin 1: entity extraction, LLM turns questions into structured JSON (intent/scenario/entities) / Plugin 1:
#              实体抽取。LLM 把用户问题转为结构化 JSON（intent/scenario/entities）。
"""

Plugin 1: 实体抽取。LLM 把用户问题转为结构化 JSON（intent/scenario/entities）。
"""
from __future__ import annotations

import json
from typing import Any

from semantic_kernel.functions import KernelArguments, kernel_function

from app.core.logging import StepEventBus
from app.llm.prompts import entity_extraction_user, ENTITY_EXTRACTION_SYSTEM
from app.llm.providers import LLMProvider


class EntityExtractionPlugin:
    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    @kernel_function(name="extract", description="从用户问题抽取实体与意图，返回 JSON")
    async def extract(
        self,
        question: str,
        arguments: KernelArguments,
    ) -> dict[str, Any]:
        bus: StepEventBus = arguments["bus"]
        await bus.emit("entity_extraction", "开始 LLM 实体抽取", {"question": question})
        text = await self._llm.chat(
            ENTITY_EXTRACTION_SYSTEM, entity_extraction_user(question)
        )
        text = text.strip().removeprefix("```json").removeprefix("```").strip()
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            # 退回：把整段当 entities.question
            data = {"intent": "general", "scenario": "general", "entities": {"raw": text}}
        await bus.emit(
            "entity_extraction",
            "实体抽取完成",
            {"intent": data.get("intent"), "entities": data.get("entities")},
        )
        return data
