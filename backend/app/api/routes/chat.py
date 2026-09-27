# @Author: RebeccaZhou
# @Description: Chat SSE route: streams step events, reference fragments and answer tokens
#              问答 SSE 路由：流式回传步骤事件/引用片段/答案 token。
from __future__ import annotations

import json
from typing import AsyncIterator

from fastapi import APIRouter, Depends
from sse_starlette.sse import EventSourceResponse

from app.core.deps import get_kernel
from app.kernel.kernel import build_kernel
from app.kernel.pipeline import GraphRAGPipeline
from app.models.schemas import ChatRequest

router = APIRouter()

@router.post("/chat")
async def chat(req: ChatRequest):
    """SSE 流：每条 event 的 data 是 JSON。

    事件类型：
      step        步骤日志
      fragments   引用片段
      token       答案 token
      done        完整答案
    """
    # 如指定 model，则临时构建使用该 provider 的 kernel
    kernel = build_kernel(req.model) if req.model else get_kernel()
    pipeline = GraphRAGPipeline(kernel)

    async def gen() -> AsyncIterator[dict]:
        async for ev in pipeline.run_stream(req.question):
            yield {"event": ev["type"], "data": json.dumps(ev, ensure_ascii=False)}

    return EventSourceResponse(gen())
