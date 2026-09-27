# @Author: RebeccaZhou
# @Description: Programmatically generates 150 evaluation cases from seed data
#              从种子数据程序生成 150 条评估用例。
"""

策略：
1. 枚举所有 (实体, 关系) 组合 → 基础用例
2. 每个基础用例加 3-5 种问句变体
3. 加入跨场景多跳查询（型号→故障→原因→方案→滤芯）
4. 加入边界用例（模糊问题、无答案、多实体比较）
"""
from __future__ import annotations

import json
import os
from itertools import combinations

SEED_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data", "seed")

def load(name: str) -> list[dict]:
    with open(os.path.join(SEED_DIR, f"{name}.json"), encoding="utf-8") as f:
        return json.load(f)

models = load("models")
filters = load("filters")
faults = load("faults")
causes = load("causes")
solutions = load("solutions")
customers = load("customers")
orders = load("orders")
batches = load("batches")
edges = load("edges")

# 建索引
edges_by_from: dict[tuple[str, str], list[dict]] = {}
edges_by_to: dict[tuple[str, str], list[dict]] = {}
for e in edges:
    fk = (e["from_label"], e["from"])
    tk = (e["to_label"], e["to"])
    edges_by_from.setdefault(fk, []).append(e)
    edges_by_to.setdefault(tk, []).append(e)

model_names = [m["name"] for m in models]
filter_codes = [f["code"] for f in filters]
fault_codes = [f["code"] for f in faults]
cause_ids = [c["id"] for c in causes]
solution_ids = [s["id"] for s in solutions]
customer_ids = [c["id"] for c in customers]
order_ids = [o["id"] for o in orders]
batch_ids = [b["id"] for b in batches]

cases: list[dict] = []
seq = 0

def add(scenario: str, question: str, expected: list[str]):
    global seq
    seq += 1
    cases.append({
        "case_id": f"{scenario[:3].upper()}-{seq:03d}",
        "scenario": scenario,
        "question": question,
        "expected_keywords": expected,
    })

# ============================================================
# 场景1：滤芯兼容 (filter_compatibility) — 目标 ~50 条
# ============================================================

# 1a. 每个型号的滤芯清单
for m in models:
    name = m["name"]
    model_filters = [
        e["to"] for e in edges_by_from.get(("Model", name), [])
        if e["type"] == "USES"
    ]
    if not model_filters:
        continue

    variants = [
        f"{name} 能用哪些滤芯？",
        f"{name} 支持的滤芯清单",
        f"{name} 的滤芯型号有哪些？",
        f"PG-{name.split('-')[1]} 净水器配什么滤芯？".replace("PG-PG-", "PG-"),
        f"{name} 净水器可以用哪些型号的滤芯？",
    ]
    for v in variants[:4]:
        add("filter_compatibility", v, model_filters)

# 1b. 反向：每个滤芯被哪些型号使用
for f in filters:
    code = f["code"]
    used_by = [
        e["from"] for e in edges_by_to.get(("Filter", code), [])
        if e["type"] == "USES"
    ]
    if not used_by:
        continue
    variants = [
        f"哪些型号使用了 {code} 滤芯？",
        f"{code} 滤芯适配哪些净水器？",
        f"哪些净水器可以用 {code}？",
    ]
    for v in variants[:3]:
        add("filter_compatibility", v, used_by)

# 1c. 多型号比较滤芯（两两组合）
for m1, m2 in combinations(model_names, 2):
    f1 = {e["to"] for e in edges_by_from.get(("Model", m1), []) if e["type"] == "USES"}
    f2 = {e["to"] for e in edges_by_from.get(("Model", m2), []) if e["type"] == "USES"}
    common = f1 & f2
    diff = f1 - f2
    if common:
        add("filter_compatibility",
            f"{m1} 和 {m2} 共用哪些滤芯？",
            list(common))
    # RO 膜比较
    ro1 = {e["to"] for e in edges_by_from.get(("Model", m1), [])
           if e["type"] == "USES" and "RO" in e["to"]}
    ro2 = {e["to"] for e in edges_by_from.get(("Model", m2), [])
           if e["type"] == "USES" and "RO" in e["to"]}
    if ro1 and ro2:
        add("filter_compatibility",
            f"{m1} 与 {m2} 的 RO 膜是否相同？",
            list(ro1 & ro2) or list(ro1 | ro2))

# 1d. 膜类型查询
for m in models:
    name = m["name"]
    uf = [e["to"] for e in edges_by_from.get(("Model", name), [])
          if e["type"] == "USES" and "UF" in e["to"]]
    ro = [e["to"] for e in edges_by_from.get(("Model", name), [])
          if e["type"] == "USES" and "RO" in e["to"]]
    nano = [e["to"] for e in edges_by_from.get(("Model", name), [])
            if e["type"] == "USES" and "Nano" in e["to"]]
    if uf:
        add("filter_compatibility", f"{name} 用的是哪种膜？", uf + ["超滤膜"])
    if nano:
        add("filter_compatibility", f"{name} 配什么膜？", nano + ["纳滤膜"])

# ============================================================
# 场景2：故障排查 (fault_diagnosis) — 目标 ~60 条
# ============================================================

# 2a. 型号 + 故障 → 原因 + 方案
for m in models:
    name = m["name"]
    model_faults = [
        e["to"] for e in edges_by_from.get(("Model", name), [])
        if e["type"] == "HAS_FAULT"
    ]
    for fc in model_faults:
        cause_ids_for_fault = [
            e["to"] for e in edges_by_from.get(("Fault", fc), [])
            if e["type"] == "CAUSED_BY"
        ]
        causes_desc = [
            next((c["description"] for c in causes if c["id"] == cid), cid)
            for cid in cause_ids_for_fault
        ]
        fault_symptom = next((f["symptom"] for f in faults if f["code"] == fc), fc)

        # 方案
        sol_ids = []
        for cid in cause_ids_for_fault:
            sol_ids.extend([
                e["to"] for e in edges_by_from.get(("Cause", cid), [])
                if e["type"] == "SOLVED_BY"
            ])
        sol_desc = [
            next((s["description"] for s in solutions if s["id"] == sid), sid)
            for sid in sol_ids
        ]
        # 方案关联滤芯
        req_filters = []
        for sid in sol_ids:
            req_filters.extend([
                e["to"] for e in edges_by_from.get(("Solution", sid), [])
                if e["type"] == "REQUIRES_FILTER"
            ])

        expected = list(set(cause_ids_for_fault + sol_ids + req_filters + causes_desc[:2] + sol_desc[:2]))
        variants = [
            f"{name} {fault_symptom}可能是什么原因？",
            f"{name} {fault_symptom}怎么排查？",
            f"{name} {fc}故障如何解决？",
            f"{name}出现{fault_symptom}怎么办？",
        ]
        for v in variants[:3]:
            add("fault_diagnosis", v, expected)

# 2b. 故障代码 → 原因 + 方案
for f in faults:
    fc = f["code"]
    symptom = f["symptom"]
    cause_ids_for_fault = [
        e["to"] for e in edges_by_from.get(("Fault", fc), [])
        if e["type"] == "CAUSED_BY"
    ]
    sol_ids = []
    for cid in cause_ids_for_fault:
        sol_ids.extend([
            e["to"] for e in edges_by_from.get(("Cause", cid), [])
            if e["type"] == "SOLVED_BY"
        ])
    req_filters = []
    for sid in sol_ids:
        req_filters.extend([
            e["to"] for e in edges_by_from.get(("Solution", sid), [])
            if e["type"] == "REQUIRES_FILTER"
        ])
    causes_desc = [
        next((c["description"] for c in causes if c["id"] == cid), cid)
        for cid in cause_ids_for_fault
    ]
    sol_desc = [
        next((s["description"] for s in solutions if s["id"] == sid), sid)
        for sid in sol_ids
    ]
    expected = list(set(cause_ids_for_fault + sol_ids + req_filters + causes_desc[:2] + sol_desc[:2]))

    variants = [
        f"故障 {fc} 的原因是什么？",
        f"FLT-{fc.split('-')[1]} 故障怎么修？",
        f"{symptom} 故障代码 {fc} 如何解决？",
        f"FLT-{fc.split('-')[1]} 排除方法？",
    ]
    for v in variants[:3]:
        add("fault_diagnosis", v, expected)

# 2c. 方案 → 需要换哪个滤芯
for s in solutions:
    sid = s["id"]
    req_filters = [
        e["to"] for e in edges_by_from.get(("Solution", sid), [])
        if e["type"] == "REQUIRES_FILTER"
    ]
    if req_filters:
        add("fault_diagnosis",
            f"{s['description']}需要换哪个滤芯？",
            req_filters)

# ============================================================
# 场景3：批次召回 (batch_recall) — 目标 ~40 条
# ============================================================

# 3a. 批次 → 召回状态 + 受影响滤芯 + 生产型号
for b in batches:
    bid = b["id"]
    affected_filters = [
        e["to"] for e in edges_by_from.get(("Batch", bid), [])
        if e["type"] == "AFFECTS"
    ]
    produced_models = [
        e["to"] for e in edges_by_from.get(("Batch", bid), [])
        if e["type"] == "PRODUCES"
    ]

    status = b["recall_status"]
    status_kw = ["召回", "recalled"] if status == "active" else [
        "none", "未召回", "未被召回", "无召回", "没有召回", "不在召回", "未在召回", "正常",
    ]
    expected = status_kw + affected_filters + produced_models

    variants = [
        f"{bid} 是否在召回？",
        f"批次 {bid} 的召回状态？",
        f"BATCH-{bid.split('-')[1]} 有问题吗？",
        f"{bid} 涉及哪些型号？",
    ]
    for v in variants[:3]:
        add("batch_recall", v, expected)

    if affected_filters:
        add("batch_recall",
            f"{bid} 涉及的滤芯编码是什么？",
            affected_filters)

# 3b. 批次 → 影响的客户订单
for b in batches:
    bid = b["id"]
    if b["recall_status"] != "active":
        continue
    # 找该批次的订单
    batch_orders = [
        e["from"] for e in edges_by_to.get(("Batch", bid), [])
        if e["type"] == "FROM_BATCH"
    ]
    # 订单 → 客户
    affected_customers = []
    for oid in batch_orders:
        affected_customers.extend([
            e["from"] for e in edges_by_to.get(("Order", oid), [])
            if e["type"] == "PLACED"
        ])

    expected = list(set(affected_customers + batch_orders + ["免费更换"]))
    if expected:
        variants = [
            f"{bid} 召回影响哪些客户的订单？",
            f"受 {bid} 影响的客户应如何处理？",
            f"{bid} 召回涉及哪些订单和客户？",
        ]
        for v in variants[:2]:
            add("batch_recall", v, expected)

# 3c. 客户 → 订单 → 批次
for cust in customers[:6]:
    cid = cust["id"]
    cust_orders = [
        e["to"] for e in edges_by_from.get(("Customer", cid), [])
        if e["type"] == "PLACED"
    ]
    for oid in cust_orders:
        order_batch = [
            e["to"] for e in edges_by_from.get(("Order", oid), [])
            if e["type"] == "FROM_BATCH"
        ]
        if order_batch:
            expected = [cid, oid] + order_batch
            add("batch_recall",
                f"{cust['name']}的订单{oid}来自哪个批次？",
                expected)

# 3d. 型号 → 生产批次
for m in models:
    name = m["name"]
    model_batches = [
        e["from"] for e in edges_by_to.get(("Model", name), [])
        if e["type"] == "PRODUCES"
    ]
    if model_batches:
        add("batch_recall",
            f"哪些批次生产了 {name}？",
            model_batches)

# 3e. 边界用例
add("batch_recall", "所有召回批次有哪些？", ["BATCH-2024C", "active"])
add("batch_recall", "有没有批次被召回？", ["BATCH-2024C", "召回"])

# ============================================================
# 输出
# ============================================================
print(f"Generated {len(cases)} test cases")

# 按场景统计
from collections import Counter
sc_counts = Counter(c["scenario"] for c in cases)
for sc, n in sc_counts.items():
    print(f"  {sc}: {n}")

# 写文件
out_path = os.path.join(os.path.dirname(__file__), "test_cases_generated.py")
with open(out_path, "w", encoding="utf-8") as f:
    f.write('"""自动生成的 150 条评估用例。"""\n')
    f.write("from app.evaluation.test_cases import EvalCase\n\n")
    f.write("GENERATED_CASES = [\n")
    for c in cases:
        kw_str = str(c["expected_keywords"])
        f.write(f'    EvalCase("{c["case_id"]}", "{c["scenario"]}", "{c["question"]}", {kw_str}),\n')
    f.write("]\n")

print(f"\nWritten to {out_path}")
