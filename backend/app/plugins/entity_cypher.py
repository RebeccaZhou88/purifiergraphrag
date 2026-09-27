# @Author: RebeccaZhou
# @Description: Plugins 1+2 merged: entity extraction and Cypher generation in one LLM call / Plugin 1+2
#              合并：一次 LLM 调用同时完成实体抽取+ Cypher 生成。
"""

Plugin 1+2 合并：一次 LLM 调用同时完成实体抽取 + Cypher 生成。

相比分离版省一次 LLM 往返（~1.3s），同时输出 JSON:
{"intent": "...", "entities": {...}, "cypher": "MATCH ... RETURN ..."}
"""
from __future__ import annotations

import json
from typing import Any

from semantic_kernel.functions import KernelArguments, kernel_function

from app.core.logging import StepEventBus
from app.llm.prompts import ENTITY_CYPHER_SYSTEM, entity_cypher_user
from app.llm.providers import LLMProvider


class EntityCypherPlugin:
    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    @kernel_function(name="extract_and_query", description="从用户问题同时抽取实体并生成 Cypher")
    async def extract_and_query(
        self,
        question: str,
        arguments: KernelArguments,
    ) -> dict[str, Any]:
        bus: StepEventBus = arguments["bus"]

        await bus.emit("entity_extraction", "开始 LLM 实体抽取 + Cypher 生成", {"question": question})
        text = await self._llm.chat(
            ENTITY_CYPHER_SYSTEM, entity_cypher_user(question), temperature=0.0
        )
        text = text.strip().removeprefix("```json").removeprefix("```").strip()

        # 解析 JSON
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            # 退回：把整段当 entities，cypher 置空
            data = {"intent": "general", "entities": {"raw": text}, "cypher": ""}

        extraction = {
            "intent": data.get("intent", "general"),
            "entities": data.get("entities", {}),
        }
        cypher = (data.get("cypher") or "").strip()

        # 清理 Cypher：去掉 ```cypher 包裹、取最长那段
        cypher = cypher.removeprefix("```cypher").removeprefix("```").strip()
        if cypher:
            parts = [p.strip() for p in cypher.split("\n\n") if p.strip()]
            if parts:
                cypher = max(parts, key=len)
            cypher = cypher.removeprefix("```").strip()

        await bus.emit(
            "entity_extraction",
            "实体抽取完成",
            {"intent": extraction.get("intent"), "entities": extraction.get("entities")},
        )
        await bus.emit("cypher_query", "生成 Cypher", {"cypher": cypher})

        return {"extraction": extraction, "cypher": cypher}
