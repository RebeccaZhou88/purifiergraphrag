# @Author: RebeccaZhou
# @Description: Plugins 1+2 merged (rule-first version) / Plugin 1+2
#              合并（规则优先版）：
"""

Plugin 1+2 合并（规则优先版）：

1. 先用规则引擎（正则 + 关键词）做实体抽取 + Cypher 模板生成 —— 零 LLM 调用
2. 规则覆盖不到时自动回退到 LLM 合并插件（EntityCypherPlugin）

这样 80%+ 的常规查询省掉第一个 LLM 调用（~2.5s），P95 直接下来。
"""
from __future__ import annotations

import json
from typing import Any

from semantic_kernel.functions import KernelArguments, kernel_function

from app.core.logging import StepEventBus
from app.llm.prompts import ENTITY_CYPHER_SYSTEM, entity_cypher_user
from app.llm.providers import LLMProvider
from app.llm.rules import build_cypher, detect_intent, extract_entities


class SmartEntityCypherPlugin:
    """规则优先 + LLM 回退的实体/Cypher 合并插件。"""

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    @kernel_function(name="extract_and_query", description="规则优先：实体抽取 + Cypher 生成")
    async def extract_and_query(
        self,
        question: str,
        arguments: KernelArguments,
    ) -> dict[str, Any]:
        bus: StepEventBus = arguments["bus"]

        # === 规则引擎 ===
        entities = extract_entities(question)
        intent = detect_intent(question, entities)
        cypher = build_cypher(intent, entities, question)

        extraction = {"intent": intent, "entities": entities}

        # 规则命中 → 直接返回，零 LLM
        if cypher:
            await bus.emit("entity_extraction", "规则引擎命中（零 LLM）", {
                "intent": intent, "entities": entities
            })
            await bus.emit("cypher_query", "规则模板命中（零 LLM）", {"cypher": cypher[:150]})
            return {"extraction": extraction, "cypher": cypher}

        # 规则未覆盖 → 回退 LLM
        await bus.emit("entity_extraction", "规则未覆盖，回退 LLM", {
            "intent": intent, "entities": entities
        })
        text = await self._llm.chat(
            ENTITY_CYPHER_SYSTEM, entity_cypher_user(question), temperature=0.0
        )
        text = text.strip().removeprefix("```json").removeprefix("```").strip()

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            data = {"intent": intent, "entities": entities, "cypher": ""}

        extraction = {
            "intent": data.get("intent", intent),
            "entities": data.get("entities", entities),
        }
        cypher = (data.get("cypher") or "").strip()
        cypher = cypher.removeprefix("```cypher").removeprefix("```").strip()
        if cypher:
            parts = [p.strip() for p in cypher.split("\n\n") if p.strip()]
            if parts:
                cypher = max(parts, key=len)
            cypher = cypher.removeprefix("```").strip()

        await bus.emit("entity_extraction", "LLM 实体抽取完成", extraction)
        await bus.emit("cypher_query", "LLM Cypher 生成完成", {"cypher": cypher[:150]})
        return {"extraction": extraction, "cypher": cypher}
