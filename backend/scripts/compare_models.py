# -*- coding: utf-8 -*-
# @Author: RebeccaZhou
# @Description: Three-model end-to-end comparison (local only, reads eval_data_*.jsonl, no API calls)
#              三模型全链路对比（纯本地，只读 eval_data_*.jsonl，不调 API）。
"""

指标分四层：
  答案质量   keyword_hit_rate(命中任一) / entity_recall(平均覆盖率) / completeness(全命中)
  检索质量   context_hit_rate / context_recall / zero_result_rate / retrieved_mean
  稳定性     cypher_valid_rate / error_rate
  性能与成本 total/ttft/四阶段的 mean·p50·p95；token 均值与合计；可选估算 USD 成本

Foundry 门户负责 LLM-judge（relevance/groundedness/retrieval）；
本脚本负责确定性指标与性能/成本汇总，两者拼成全链路结论。

用法（backend 目录）：
    python scripts/compare_models.py
    python scripts/compare_models.py --providers deepseek,qwen
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
EVAL_DIR = BACKEND / "data" / "eval"
PROVIDERS = ["deepseek", "qwen", "azure_openai"]
SCENARIOS = ["filter_compatibility", "fault_diagnosis", "batch_recall"]

# 可选：每 1M token 的美元单价（input/output）。留空则只输出 token 不估成本。
# 价格随官方调整，请按实际部署/代理价格填写。
PRICING = {
    # "deepseek":     (0.27, 1.10),
    # "qwen":         (..., ...),
    "azure_openai": (0.40, 1.60),  # gpt-4.1-mini 公开价（参考）
}

def kws(gt: str) -> list[str]:
    return [k.strip().lower() for k in (gt or "").split("|") if k.strip()]

def hit_fraction(text: str, keywords: list[str]) -> float:
    if not keywords:
        return 0.0
    t = (text or "").lower()
    return sum(1 for k in keywords if k in t) / len(keywords)

def pct(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    i = min(len(s) - 1, int(round((len(s) - 1) * q)))
    return s[i]

def agg_latency(values: list[float]) -> dict:
    values = [v for v in values if v is not None]
    if not values:
        return {"mean": 0, "p50": 0, "p95": 0, "max": 0}
    return {
        "mean": round(statistics.mean(values)),
        "p50": round(statistics.median(values)),
        "p95": round(pct(values, 0.95)),
        "max": round(max(values)),
    }

def compute(provider: str) -> dict:
    path = EVAL_DIR / f"eval_data_{provider}.jsonl"
    if not path.exists():
        raise SystemExit(f"缺少 {path}")
    rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    n = len(rows)

    kw_hit, ent_recall, complete = [], [], []
    ctx_hit, ctx_recall = [], []
    by_scenario_recall: dict[str, list[float]] = {s: [] for s in SCENARIOS}
    zero_result, cypher_valid, error = 0, 0, 0
    retrieved = []

    for r in rows:
        k = kws(r.get("ground_truth", ""))
        resp = r.get("response", "")
        ctx = r.get("context", "")

        rf = hit_fraction(resp, k)
        cf = hit_fraction(ctx, k)
        ent_recall.append(rf)
        ctx_recall.append(cf)
        kw_hit.append(1.0 if rf > 0 else 0.0)
        ctx_hit.append(1.0 if cf > 0 else 0.0)
        complete.append(1.0 if k and rf >= 1.0 else 0.0)

        sc = r.get("metadata", {}).get("scenario")
        if sc in by_scenario_recall:
            by_scenario_recall[sc].append(rf)

        if (r.get("retrieved_count") or 0) == 0:
            zero_result += 1
        retrieved.append(r.get("retrieved_count") or 0)

        cy = (r.get("cypher") or "").upper()
        if "MATCH" in cy and "RETURN" in cy:
            cypher_valid += 1
        if r.get("status") != "ok":
            error += 1

    total = [r.get("total_latency_ms") for r in rows]
    ttft = [r.get("ttft_ms") for r in rows]
    t_ext = [r.get("t_extract_cypher_ms") for r in rows]
    t_exec = [r.get("t_cypher_exec_ms") for r in rows]
    t_ctx = [r.get("t_context_ms") for r in rows]
    t_gen = [r.get("t_generate_ms") for r in rows]

    pt = [r.get("prompt_tokens") or 0 for r in rows]
    ct = [r.get("completion_tokens") or 0 for r in rows]
    tt = [r.get("total_tokens") or 0 for r in rows]

    price = PRICING.get(provider)
    cost = None
    if price:
        pin, pout = price
        cost = (sum(pt) / 1e6 * pin) + (sum(ct) / 1e6 * pout)

    return {
        "provider": provider,
        "model": rows[0].get("metadata", {}).get("model", ""),
        "n": n,
        # 答案质量（%）
        "keyword_hit_rate": round(100 * statistics.mean(kw_hit), 1),
        "entity_recall": round(100 * statistics.mean(ent_recall), 1),
        "completeness": round(100 * statistics.mean(complete), 1),
        # 检索（%）
        "context_hit_rate": round(100 * statistics.mean(ctx_hit), 1),
        "context_recall": round(100 * statistics.mean(ctx_recall), 1),
        "zero_result_rate": round(100 * zero_result / n, 1),
        "retrieved_mean": round(statistics.mean(retrieved), 2),
        # 稳定性（%）
        "cypher_valid_rate": round(100 * cypher_valid / n, 1),
        "error_rate": round(100 * error / n, 1),
        # 分场景实体召回（%）
        **{
            f"recall_{s}": round(100 * statistics.mean(by_scenario_recall[s]), 1)
            if by_scenario_recall[s] else None
            for s in SCENARIOS
        },
        # 性能 ms
        "total": agg_latency(total),
        "ttft": agg_latency(ttft),
        "t_extract_cypher": agg_latency(t_ext),
        "t_cypher_exec": agg_latency(t_exec),
        "t_context": agg_latency(t_ctx),
        "t_generate": agg_latency(t_gen),
        # token
        "prompt_tokens_avg": round(statistics.mean(pt)),
        "completion_tokens_avg": round(statistics.mean(ct)),
        "total_tokens_avg": round(statistics.mean(tt)),
        "total_tokens_sum": sum(tt),
        "cost_usd_est": round(cost, 4) if cost is not None else None,
    }

def print_table(results: list[dict]) -> None:
    def row(label: str, key, sub="mean", fmt="{:.0f}"):
        cells = [label]
        for m in results:
            v = m[key]
            if isinstance(v, dict):
                v = v[sub]
            cells.append(fmt.format(v) if isinstance(v, (int, float)) else "-")
        return cells

    provs = [m["provider"] for m in results]
    header = ["指标", *provs]

    sections = [
        ("规模", [
            ["用例数", "n", "", "{}"],
            ["模型", "model", "", "{}"],
        ]),
        ("答案质量 (%)  [keyword=任一命中, recall=平均覆盖率, completeness=全命中]", [
            ["keyword_hit_rate", "keyword_hit_rate", "", "{:.1f}"],
            ["entity_recall", "entity_recall", "", "{:.1f}"],
            ["completeness(严格)", "completeness", "", "{:.1f}"],
        ]),
        ("检索质量 (%)", [
            ["context_hit_rate", "context_hit_rate", "", "{:.1f}"],
            ["context_recall", "context_recall", "", "{:.1f}"],
            ["zero_result_rate", "zero_result_rate", "", "{:.1f}"],
            ["retrieved_count 均值", "retrieved_mean", "", "{:.2f}"],
        ]),
        ("分场景实体召回 (%)", [
            ["滤芯兼容", "recall_filter_compatibility", "", "{:.1f}"],
            ["故障诊断", "recall_fault_diagnosis", "", "{:.1f}"],
            ["批次召回(多跳)", "recall_batch_recall", "", "{:.1f}"],
        ]),
        ("稳定性 (%)", [
            ["cypher_valid", "cypher_valid_rate", "", "{:.1f}"],
            ["error_rate", "error_rate", "", "{:.1f}"],
        ]),
        ("端到端延迟 (ms)", [
            ["total mean", "total", "mean", "{:.0f}"],
            ["total p50", "total", "p50", "{:.0f}"],
            ["total p95", "total", "p95", "{:.0f}"],
            ["total max", "total", "max", "{:.0f}"],
        ]),
        ("TTFT 首token (ms)", [
            ["ttft mean", "ttft", "mean", "{:.0f}"],
            ["ttft p95", "ttft", "p95", "{:.0f}"],
        ]),
        ("分阶段 mean (ms)", [
            ["抽取+生成Cypher", "t_extract_cypher", "mean", "{:.0f}"],
            ["Cypher执行(Neo4j)", "t_cypher_exec", "mean", "{:.0f}"],
            ["上下文组装", "t_context", "mean", "{:.0f}"],
            ["答案生成", "t_generate", "mean", "{:.0f}"],
        ]),
        ("成本 (token)", [
            ["prompt/条", "prompt_tokens_avg", "", "{:.0f}"],
            ["completion/条", "completion_tokens_avg", "", "{:.0f}"],
            ["total/条", "total_tokens_avg", "", "{:.0f}"],
            ["total 合计", "total_tokens_sum", "", "{:.0f}"],
            ["估算成本 USD", "cost_usd_est", "", "{:.4f}"],
        ]),
    ]

    widths = [max(len(header[0]), 46)] + [max(len(p), 14) for p in provs]

    def line(cells):
        return "  ".join(str(c).ljust(widths[i]) for i, c in enumerate(cells))

    print("\n" + "=" * 90)
    print("三模型全链路对比（数据来源 eval_data_*.jsonl）")
    print("=" * 90)
    print(line(header))
    print("-" * 90)
    for title, rows in sections:
        print(f"\n■ {title}")
        for label, key, sub, fmt in rows:
            cells = [label]
            for m in results:
                v = m.get(key)
                if isinstance(v, dict):
                    v = v.get(sub)
                cells.append(fmt.format(v) if isinstance(v, (int, float)) else (v or "-"))
            print(line(cells))

def flatten(m: dict) -> dict:
    """拍平用于 CSV：latency 字典展开为 xxx_mean/p50/p95/max。"""
    out = {}
    for k, v in m.items():
        if isinstance(v, dict):
            for kk, vv in v.items():
                out[f"{k}_{kk}"] = vv
        else:
            out[k] = v
    return out

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--providers", default=",".join(PROVIDERS))
    args = ap.parse_args()
    providers = [p.strip() for p in args.providers.split(",") if p.strip()]

    results = [compute(p) for p in providers]
    print_table(results)

    flat = [flatten(m) for m in results]
    keys = list(flat[0].keys())
    csv_path = EVAL_DIR / "model_comparison.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(flat)
    json_path = EVAL_DIR / "model_comparison.json"
    json_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n已导出: {csv_path}\n        {json_path}")
    print("质量 LLM-judge(relevance/groundedness/retrieval) 见 Foundry 门户 Compare runs。")

if __name__ == "__main__":
    main()
