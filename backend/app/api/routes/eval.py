# @Author: RebeccaZhou
# @Description: Evaluation route: triggers batch evaluation and streams per-case results
#              评估路由：触发批量评估并流式回传每个用例结果。
from __future__ import annotations

import json
from typing import AsyncIterator

from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse

from app.evaluation.runner import EvalRunner
from app.evaluation.test_cases import get_cases
from app.models.schemas import EvalRequest

router = APIRouter()

@router.get("/eval/cases")
async def list_eval_cases():
    """返回全部评估用例元信息（供前端面板展示用例总数与场景分布）。"""
    cases = get_cases()
    by_scenario: dict[str, int] = {}
    for c in cases:
        by_scenario[c.scenario] = by_scenario.get(c.scenario, 0) + 1
    return {
        "total": len(cases),
        "by_scenario": by_scenario,
        "cases": [
            {"case_id": c.case_id, "scenario": c.scenario, "question": c.question}
            for c in cases
        ],
    }

@router.post("/eval")
async def run_eval(req: EvalRequest):
    runner = EvalRunner(provider=req.model, scenario_filter=req.scenario)

    async def gen() -> AsyncIterator[dict]:
        async for item in runner.run():
            yield {"event": item["type"], "data": json.dumps(item, ensure_ascii=False)}

    return EventSourceResponse(gen())
