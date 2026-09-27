# -*- coding: utf-8 -*-
# @Author: RebeccaZhou
# @Description: Runs the GraphRAG pipeline to produce the Foundry eval dataset eval_data_{provider}.jsonl
#              跑 GraphRAG 流水线，生成 Foundry 评估数据集 eval_data_{provider}.jsonl。
"""
字段见 README 第六节（基础四列 + 检索/状态/性能/成本/元信息，共 20 列）。

在 backend/ 目录运行：
    set PYTHONPATH=.
    python scripts/generate_eval_data.py --provider deepseek           # 全量
    python scripts/generate_eval_data.py --provider deepseek --limit 3 # 小批量验证
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.evaluation.test_cases import get_cases  # noqa: E402
from app.kernel.kernel import build_kernel  # noqa: E402
from app.kernel.pipeline import GraphRAGPipeline  # noqa: E402
from app.llm.providers import get_provider  # noqa: E402

# 标记“Cypher 已生成”的事件消息（区别于后续“执行/查询”事件）
_CYPHER_BUILT_MARKS = ("模板命中", "生成完成", "生成 Cypher")

async def run_one(pipeline: GraphRAGPipeline, question: str) -> dict[str, Any]:
    """跑单条用例，从事件流时间戳还原各阶段耗时与中间产物。"""
    start = time.time()
    answer, cypher, cypher_error = "", "", ""
    fragments: list[dict] = []
    intent = ""

    # 时间锚点（wall clock 秒，与事件 ts 同源）
    extract_start = cypher_built = exec_start = exec_end = None
    context_end = gen_start = gen_end = first_token = None
    row_count = 0

    try:
        async for ev in pipeline.run_stream(question):
            etype = ev.get("type")

            if etype == "step":
                step, msg, data, ts = (
                    ev.get("step"), ev.get("message", ""), ev.get("data") or {}, ev.get("ts"),
                )

                if step == "entity_extraction":
                    if extract_start is None:
                        extract_start = ts
                    if isinstance(data, dict) and data.get("intent"):
                        intent = data["intent"]

                elif step == "cypher_query":
                    if cypher_built is None and any(m in msg for m in _CYPHER_BUILT_MARKS):
                        cypher_built = ts
                        if isinstance(data, dict) and data.get("cypher") and not cypher:
                            cypher = data["cypher"]
                    elif "执行 Cypher" in msg:
                        exec_start = ts
                    elif "Cypher 执行失败" in msg:
                        cypher_error = str(data.get("error") or msg)
                    elif "查询完成" in msg:
                        exec_end = ts
                        row_count = int(data.get("row_count") or 0)

                elif step == "graph_context":
                    context_end = ts

                elif step == "llm_generation":
                    if "开始流式生成" in msg:
                        gen_start = ts
                    elif "异常" in msg:
                        cypher_error = cypher_error or str(data or msg)
                    elif "生成完成" in msg:
                        gen_end = ts

            elif etype == "fragments":
                fragments = ev.get("fragments", []) or []
                full_cy = ev.get("cypher")  # 完整 cypher（事件里的被截断到 150）
                if full_cy:
                    cypher = full_cy

            elif etype == "token":
                if first_token is None:
                    first_token = time.time()

            elif etype == "done":
                answer = ev.get("answer", "") or ""
    except Exception as e:  # 流水线整体失败也要落一条，便于统计失败率
        cypher_error = cypher_error or f"pipeline: {e!r}"

    done = time.time()

    def ms(a: float | None, b: float | None) -> int | None:
        return int(round((a - b) * 1000)) if (a is not None and b is not None) else None

    # fragments 元素是 {"id","title","content": <记录dict>}，序列化 content 作为 context
    context_text = "\n".join(
        json.dumps(fr.get("content"), ensure_ascii=False, default=str)
        for fr in fragments
        if isinstance(fr, dict) and fr.get("content") is not None
    )
    retrieved_count = len(fragments) or row_count

    if cypher_error:
        status = "error"
    elif not answer.strip():
        status = "empty"
    else:
        status = "ok"

    return {
        "answer": answer,
        "cypher": cypher,
        "context": context_text,
        "retrieved_count": retrieved_count,
        "status": status,
        "cypher_error": cypher_error,
        "intent": intent,
        "timing": {
            "total_latency_ms": int(round((done - start) * 1000)),
            "ttft_ms": ms(first_token, gen_start),
            "t_extract_cypher_ms": ms(cypher_built, extract_start),
            "t_cypher_exec_ms": ms(exec_end, exec_start),
            "t_context_ms": ms(context_end, exec_end if exec_end is not None else cypher_built),
            "t_generate_ms": ms(gen_end, gen_start),
        },
    }

async def run(provider: str, limit: int | None) -> None:
    pipeline = GraphRAGPipeline(build_kernel(provider))
    llm = get_provider(provider)  # 与 kernel 内同一缓存单例，读取 token 累加器
    cases = get_cases()
    if limit:
        cases = cases[:limit]

    OUT = Path(__file__).resolve().parents[1] / "data" / "eval" / f"eval_data_{provider}.jsonl"
    OUT.parent.mkdir(parents=True, exist_ok=True)
    run_ts = datetime.now(timezone.utc).isoformat()

    with OUT.open("w", encoding="utf-8") as f:
        for i, case in enumerate(cases, 1):
            llm.reset_usage()
            r = await run_one(pipeline, case.question)
            u = dict(llm.usage)

            row = {
                "id": case.case_id,
                "query": case.question,
                "response": r["answer"],
                "context": r["context"],
                "ground_truth": "|".join(case.expected_keywords),
                "cypher": r["cypher"],
                "retrieved_count": r["retrieved_count"],
                "status": r["status"],
                "cypher_error": r["cypher_error"],
                **r["timing"],
                "prompt_tokens": u["prompt_tokens"],
                "completion_tokens": u["completion_tokens"],
                "total_tokens": u["total_tokens"],
                "metadata": {
                    "scenario": case.scenario,
                    "case_id": case.case_id,
                    "intent": r["intent"],
                    "provider": provider,
                    "model": llm.model_name,
                    "stub": llm._stub_mode,
                    "run_ts": run_ts,
                },
            }
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            t = r["timing"]
            print(
                f"[{i}/{len(cases)}] {case.case_id} {r['status']:<5} "
                f"total={t['total_latency_ms']}ms ttft={t['ttft_ms']}ms "
                f"recs={r['retrieved_count']} ctx={len(r['context'])}字 "
                f"tokens={u['total_tokens']}"
            )

    print(f"\n导出 {len(cases)} 条 → {OUT}")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", default="deepseek")
    ap.add_argument("--limit", type=int, default=None, help="只跑前 N 条，用于验证")
    args = ap.parse_args()
    asyncio.run(run(args.provider, args.limit))
