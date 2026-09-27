# @Author: RebeccaZhou
# @Description: Evaluation runner: executes each case and streams progress and summary
#              评估执行器：跑每条用例，流式产出进度 + 汇总。
from __future__ import annotations

import time
from typing import Any, AsyncIterator

from app.core.logging import logger
from app.kernel.kernel import build_kernel
from app.kernel.pipeline import GraphRAGPipeline
from . import EvalCase
from .metrics import AggMetric, CaseMetric, check_passed, rank_by
from .test_cases import get_cases

class EvalRunner:
    def __init__(self, provider: str | None = None, scenario_filter: str | None = None) -> None:
        self.provider = provider
        self.scenario_filter = scenario_filter

    async def run(self) -> AsyncIterator[dict[str, Any]]:
        cases = get_cases(self.scenario_filter)
        kernel = build_kernel(self.provider)
        pipeline = GraphRAGPipeline(kernel)

        agg = AggMetric()
        results: list[CaseMetric] = []

        for case in cases:
            t0 = time.perf_counter()
            answer = ""
            try:
                async for ev in pipeline.run_stream(case.question):
                    if ev["type"] == "done":
                        answer = ev.get("answer", "")
            except Exception as e:
                logger.warning(f"用例 {case.case_id} 执行失败: {e}")
                answer = f"[ERROR] {e}"
            elapsed_ms = int((time.perf_counter() - t0) * 1000)

            passed = check_passed(answer, case.expected_keywords)
            m = CaseMetric(
                case_id=case.case_id,
                scenario=case.scenario,
                question=case.question,
                expected_keywords=case.expected_keywords,
                answer=answer,
                passed=passed,
                latency_ms=elapsed_ms,
            )
            results.append(m)
            agg.total += 1
            if passed:
                agg.passed += 1
            agg.latencies.append(elapsed_ms)

            yield {"type": "case", "case": _case_to_dict(m)}

        # 按最新排名升序
        ranked = rank_by(results)
        yield {"type": "summary", "metrics": agg.to_dict(), "ranked": [_case_to_dict(m) for m in ranked]}

def _case_to_dict(m: CaseMetric) -> dict[str, Any]:
    return {
        "case_id": m.case_id,
        "scenario": m.scenario,
        "question": m.question,
        "expected_keywords": m.expected_keywords,
        "answer": m.answer,
        "passed": m.passed,
        "latency_ms": m.latency_ms,
        "rank": m.rank,
    }
