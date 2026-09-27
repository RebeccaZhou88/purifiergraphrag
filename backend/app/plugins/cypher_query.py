# @Author: RebeccaZhou
# @Description: Plugin 2: Cypher multi-hop query execution / Plugin 2: Cypher
#              多跳查询。两种模式：
"""

Plugin 2: Cypher 多跳查询。两种模式：
- query: 老模式，LLM 根据抽取结果生成 Cypher 并执行
- execute_only: 新模式，直接执行传入的 Cypher（由 EntityCypherPlugin 合并生成）
"""
from __future__ import annotations

import json
from typing import Any

from semantic_kernel.functions import KernelArguments, kernel_function

from app.core.logging import StepEventBus
from app.graph.neo4j_client import Neo4jClient
from app.llm.prompts import CYPHER_GENERATION_SYSTEM, cypher_generation_user
from app.llm.providers import LLMProvider


class CypherQueryPlugin:
    def __init__(self, llm: LLMProvider, neo4j: Neo4jClient) -> None:
        self._llm = llm
        self._neo4j = neo4j

    @kernel_function(name="execute", description="直接执行传入的 Cypher 查询（合并流程专用）")
    async def execute(
        self,
        cypher: str,
        arguments: KernelArguments,
    ) -> dict[str, Any]:
        """纯执行模式：跳过 LLM 生成，直接跑 Cypher。"""
        bus: StepEventBus = arguments["bus"]
        cypher = (cypher or "").strip()
        if not cypher:
            await bus.emit("cypher_query", "Cypher 为空，跳过执行", {})
            return {"cypher": "", "records": []}

        await bus.emit("cypher_query", "执行 Cypher", {"cypher": cypher[:150]})
        try:
            records = await self._neo4j.run(cypher)
        except Exception as e:
            await bus.emit("cypher_query", "Cypher 执行失败", {"cypher": cypher, "error": str(e)})
            records = []
        await bus.emit("cypher_query", "查询完成", {"row_count": len(records)})
        return {"cypher": cypher, "records": records}

    @kernel_function(name="query", description="根据抽取结果生成并执行 Cypher 多跳查询（旧模式，保留兼容）")
    async def query(
        self,
        extraction: dict[str, Any],
        arguments: KernelArguments,
    ) -> dict[str, Any]:
        bus: StepEventBus = arguments["bus"]
        await bus.emit("cypher_query", "生成 Cypher", {"extraction": extraction})
        cypher = await self._llm.chat(
            CYPHER_GENERATION_SYSTEM,
            cypher_generation_user(json.dumps(extraction, ensure_ascii=False)),
            temperature=0.0,
        )
        cypher = cypher.strip().removeprefix("```cypher").removeprefix("```").strip()
        # 按空行分割后取最长的那段（更可能是完整 Cypher）
        parts = [p.strip() for p in cypher.split("\n\n") if p.strip()]
        if parts:
            cypher = max(parts, key=len)
        cypher = cypher.removeprefix("```").strip()

        await bus.emit("cypher_query", "执行 Cypher", {"cypher": cypher[:150]})
        try:
            records = await self._neo4j.run(cypher)
        except Exception as e:
            await bus.emit("cypher_query", "Cypher 执行失败", {"cypher": cypher, "error": str(e)})
            records = []
        await bus.emit("cypher_query", "查询完成", {"row_count": len(records)})
        return {"cypher": cypher, "records": records}
