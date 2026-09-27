# @Author: RebeccaZhou
# @Description: Plugin 3: graph context assembly, organizes Cypher records into structured citation fragments / Plugin 3:
#              图上下文组装。把 Cypher 记录整理为结构化片段列表(引用片段)。
"""

Plugin 3: 图上下文组装。把 Cypher 记录整理为结构化片段列表(引用片段)。
"""
from __future__ import annotations

from typing import Any

from semantic_kernel.functions import KernelArguments, kernel_function

from app.core.logging import StepEventBus


class GraphContextPlugin:
    @kernel_function(name="assemble", description="把 Cypher 结果组装为引用片段列表")
    async def assemble(
        self,
        cypher_result: dict[str, Any],
        arguments: KernelArguments,
    ) -> dict[str, Any]:
        bus: StepEventBus = arguments["bus"]
        records: list[dict[str, Any]] = cypher_result.get("records", [])
        fragments = []
        for idx, rec in enumerate(records):
            fragments.append(
                {
                    "id": f"ref-{idx + 1}",
                    "title": f"图谱记录 #{idx + 1}",
                    "content": rec,
                }
            )
        await bus.emit(
            "graph_context",
            "图上下文组装完成",
            {"fragments": len(fragments)},
        )
        return {
            "cypher": cypher_result.get("cypher", ""),
            "fragments": fragments,
            "context_json": _stringify(records),
        }


def _stringify(records: list[dict[str, Any]]) -> str:
    """把记录紧凑序列化为字符串喂给答案生成 LLM。"""
    import json

    return json.dumps(records, ensure_ascii=False, default=str)
