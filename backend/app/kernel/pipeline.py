# @Author: RebeccaZhou
# @Description: Orchestration: entity extraction + Cypher generation-> Cypher execution -> context assembly -> LLM streaming
#              编排：合并实体抽取+Cypher 生成 → Cypher 执行 → 图上下文组装 → LLM 流式生成。
"""

优化：把原来两次 LLM 调用（实体抽取 + Cypher 生成）合并为一次，省 ~1.3s。
CypherQueryPlugin 降级为纯执行器（execute 方法），不再做 LLM 生成。
"""
from __future__ import annotations

from typing import Any, AsyncIterator

from semantic_kernel import Kernel
from semantic_kernel.functions import KernelArguments
from semantic_kernel.functions.function_result import FunctionResult

from app.core.logging import StepEventBus

class GraphRAGPipeline:
    def __init__(self, kernel: Kernel) -> None:
        self._kernel = kernel

    async def run_stream(self, question: str) -> AsyncIterator[dict[str, Any]]:
        """运行整条流水线并流式产出事件。

        产出的事件结构：
          {type: "step", step, message, data, ts}   # 步骤日志
          {type: "fragments", fragments}            # 引用片段
          {type: "token", text}                     # 答案 token
          {type: "done", answer}                     # 结束 + 完整答案
        """
        bus = StepEventBus()

        # 1. 合并：实体抽取 + Cypher 生成（一次 LLM 调用，省一次往返）
        result = await self._kernel.invoke(
            plugin_name="entity_cypher",
            function_name="extract_and_query",
            arguments=KernelArguments(bus=bus, question=question),
        )
        merged = _value(result)
        extraction = merged.get("extraction", {})
        cypher = merged.get("cypher", "")
        for ev in bus.drain_ready():
            yield {"type": "step", **ev}

        # 2. Cypher 执行（纯执行，跳过 LLM 生成）
        result = await self._kernel.invoke(
            plugin_name="cypher",
            function_name="execute",
            arguments=KernelArguments(bus=bus, cypher=cypher),
        )
        cypher_result = _value(result)
        for ev in bus.drain_ready():
            yield {"type": "step", **ev}

        # 3. 图上下文组装（无 LLM）
        result = await self._kernel.invoke(
            plugin_name="context",
            function_name="assemble",
            arguments=KernelArguments(bus=bus, cypher_result=cypher_result),
        )
        context = _value(result)
        for ev in bus.drain_ready():
            yield {"type": "step", **ev}

        fragments = context.get("fragments", []) if context else []
        yield {"type": "fragments", "fragments": fragments,
               "cypher": (context or {}).get("cypher", "")}

        # 4. LLM 流式生成（原生 async-generator kernel function）
        full: list[str] = []
        async for chunk in self._kernel.invoke_stream(
            plugin_name="generator",
            function_name="generate_stream",
            arguments=KernelArguments(bus=bus, question=question, context=context),
        ):
            token = _stream_token(chunk)
            if token:
                full.append(token)
                yield {"type": "token", "text": token}
            for ev in bus.drain_ready():
                yield {"type": "step", **ev}
        for ev in bus.drain_ready():
            yield {"type": "step", **ev}

        yield {"type": "done", "answer": "".join(full)}

def _value(result: Any) -> Any:
    """从 SK FunctionResult 取出底层返回值。"""
    if result is None:
        return None
    if isinstance(result, FunctionResult):
        return result.value
    return result

def _stream_token(chunk: Any) -> str:
    """invoke_stream 对原生 async-generator 直接 yield 原始值（token 字符串）。"""
    if isinstance(chunk, str):
        return chunk
    if chunk is None:
        return ""
    for attr in ("content", "text"):
        v = getattr(chunk, attr, None)
        if isinstance(v, str):
            return v
    return str(chunk)
