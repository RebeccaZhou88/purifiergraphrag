# @Author: RebeccaZhou
# @Description: Rule-based entity extraction + templated Cypher generation (zero LLM calls, saves ~2.5s)
#              规则式实体抽取 + 模板化 Cypher 生成（零 LLM 调用，省 ~2.5s）。
"""

策略：
1. 正则匹配已知实体模式（PG-XXX, FC-XXX, BATCH-XXXX 等）
2. 关键词匹配意图（滤芯兼容 / 故障排查 / 批次召回）
3. (intent, entity_type) → 预写 Cypher 模板

当规则匹配不到时，自动回退到 LLM 合并插件（保证不崩）。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app.ingest.entity_dict import entity_dict

# --- 实体正则 ---
ENTITY_PATTERNS: dict[str, list[str]] = {
    "Model":      [r"PG-[A-Z]\d{3}"],
    "Filter":     [r"FC-[A-Z]{2,3}\d{2}"],
    "Fault":      [r"FLT-\d{3}"],
    "Cause":      [r"CS-\d{3}"],
    "Solution":   [r"SL-\d{3}"],
    "Customer":   [r"CUST-\d{4}"],
    "Order":      [r"ORD-\d{5}"],
    "Batch":      [r"BATCH-\d{4}[A-Z]"],
}

# --- 症状→故障 匹配（问句含症状文本时精确定位故障，避免查出全部故障） ---
_SYMPTOM_STOPWORDS = ("明显", "严重", "比较", "非常", "有点", "有些", "突然", "总是", "一直")
_FAULT_SYMPTOMS: list[tuple[str, str]] = []

def _load_fault_symptoms() -> None:
    path = Path(__file__).resolve().parents[2] / "data" / "seed" / "faults.json"
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
        _FAULT_SYMPTOMS.extend((r["code"], r["symptom"]) for r in rows)
    except (OSError, ValueError, KeyError):
        pass  # 加载失败时仅退化为不做症状匹配

_load_fault_symptoms()

def find_faults_by_symptom(question: str) -> list[str]:
    """问句包含故障症状文本（忽略程度副词）→ 返回故障编码列表。

    优先使用从图谱动态加载的症状词典（客户真实数据）；
    词典未就绪时回退到 seed/faults.json（演示数据）。
    """
    if entity_dict.is_ready() and entity_dict.symptom_count:
        return entity_dict.find_faults(question)
    q = question
    for w in _SYMPTOM_STOPWORDS:
        q = q.replace(w, "")
    return [code for code, sym in _FAULT_SYMPTOMS if sym and sym in q]

# --- 意图关键词 ---
INTENT_KEYWORDS: dict[str, list[str]] = {
    "filter_compatibility": ["滤芯", "用哪些", "哪些型号", "适配", "兼容", "膜", "滤芯清单", "能用", "使用了"],
    "fault_diagnosis":      ["故障", "坏了", "不出水", "漏水", "异味", "制水量", "报警", "排查", "原因", "怎么办", "解决"],
    "batch_recall":         ["召回", "批次", "影响", "客户", "订单", "处理", "免费更换", "涉及"],
}

def _regex_extract_entities(question: str) -> dict[str, list[str]]:
    """内置正则抽取（演示编码兜底路径）。"""
    result: dict[str, list[str]] = {}
    for etype, patterns in ENTITY_PATTERNS.items():
        values = []
        for pat in patterns:
            values.extend(re.findall(pat, question, re.IGNORECASE))
        if values:
            result[etype] = list(dict.fromkeys(values))  # 去重保序
    return result

def extract_entities(question: str) -> dict[str, list[str]]:
    """抽取问句中的实体，返回 {类型: [值列表]}。

    优先用从图谱动态加载的实体编码表（Trie 匹配，客户编码零改动）；
    动态词典未就绪（图不可用/启动未完成）时回退内置正则。
    """
    if entity_dict.is_ready():
        return entity_dict.extract(question)
    return _regex_extract_entities(question)

def detect_intent(question: str, entities: dict[str, list[str]]) -> str:
    """基于关键词 + 实体类型推断意图。"""
    q = question.lower()

    # 先看实体类型——某些实体强关联场景
    if "Batch" in entities:
        return "batch_recall"
    if "Fault" in entities:
        return "fault_diagnosis"

    # 关键词匹配
    scores: dict[str, int] = {}
    for intent, kws in INTENT_KEYWORDS.items():
        scores[intent] = sum(1 for kw in kws if kw in q)

    # Model + 故障关键词 → fault_diagnosis
    if "Model" in entities and scores.get("fault_diagnosis", 0) > 0:
        return "fault_diagnosis"

    # Model + 滤芯关键词 → filter_compatibility
    if "Model" in entities and scores.get("filter_compatibility", 0) > 0:
        return "filter_compatibility"

    best = max(scores, key=scores.get)
    if scores[best] > 0:
        return best
    return "general"

# ============================================================
# Cypher 模板库：(intent, entity_types) → Cypher 模板
# ============================================================

def build_cypher(intent: str, entities: dict[str, list[str]], question: str = "") -> str | None:
    """根据意图 + 实体组合，选择并填充 Cypher 模板。返回 None 表示规则覆盖不到。"""

    def first(k: str) -> str:
        vs = entities.get(k, [])
        return vs[0] if vs else ""

    def all_list(k: str) -> list[str]:
        return entities.get(k, [])

    def act(v: str) -> str:
        # 生命周期过滤：seed 数据无 _lifecycle 属性（null），coalesce 兜底为 active；
        # 只有被 retire_missing 显式标记 inactive 的节点才被排除
        return f"coalesce({v}._lifecycle, 'active') = 'active'"

    # --- 方案 → 滤芯（"更换XX需要换哪个滤芯"）---
    if not entities and "换哪个滤芯" in question:
        kw = question.split("需要换哪个滤芯")[0].split("要换哪个滤芯")[0]
        for w in ("免费更换", "免费替换", "更换", "替换", "免费"):
            if kw.startswith(w):
                kw = kw[len(w):]
                break
        kw = kw.strip().rstrip("，, ")
        if kw:
            return (
                f"MATCH (s:Solution)-[:REQUIRES_FILTER]->(f:Filter) "
                f"WHERE s.description CONTAINS '{kw}' AND {act('s')} AND {act('f')} "
                f"RETURN s.description AS solution, f.code AS filter_code, f.type AS filter_type"
            )

    # --- 滤芯兼容 ---
    if intent == "filter_compatibility":
        models = all_list("Model")
        filters = all_list("Filter")

        if models and not filters:
            # 型号 → 滤芯清单
            if len(models) == 1:
                return (
                    f"MATCH (m:Model {{name: '{models[0]}'}})-[:USES]->(f:Filter) "
                    f"WHERE {act('m')} AND {act('f')} "
                    f"RETURN f.code AS filter_code, f.type AS filter_type"
                )
            else:
                # 多型号比较
                names = ", ".join(f"'{n}'" for n in models)
                return (
                    f"MATCH (m:Model)-[:USES]->(f:Filter) "
                    f"WHERE m.name IN [{names}] AND {act('m')} AND {act('f')} "
                    f"RETURN m.name AS model_name, f.code AS filter_code, f.type AS filter_type"
                )

        if filters and not models:
            # 滤芯 → 哪些型号用
            code = filters[0]
            return (
                f"MATCH (f:Filter {{code: '{code}'}})<-[:USES]-(m:Model) "
                f"WHERE {act('f')} AND {act('m')} "
                f"RETURN m.name AS model_name, f.code AS filter_code"
            )

        if models and filters:
            # 型号 + 滤芯 → 比较/检查
            m, f = models[0], filters[0]
            return (
                f"MATCH (m:Model {{name: '{m}'}})-[:USES]->(f:Filter {{code: '{f}'}}) "
                f"WHERE {act('m')} AND {act('f')} "
                f"RETURN m.name AS model_name, f.code AS filter_code, f.type AS filter_type"
            )

        # 只有 Model（多型号比较 RO 膜等）
        if len(models) >= 2:
            names = ", ".join(f"'{n}'" for n in models)
            return (
                f"MATCH (m:Model)-[:USES]->(f:Filter) "
                f"WHERE m.name IN [{names}] AND (f.type CONTAINS '膜' OR f.code CONTAINS 'RO') "
                    f"AND {act('m')} AND {act('f')} "
                f"RETURN m.name AS model_name, f.code AS filter_code, f.type AS filter_type"
            )

    # --- 故障排查 ---
    if intent == "fault_diagnosis":
        models = all_list("Model")
        faults = all_list("Fault")

        # Model + Fault 组合（先匹配，最具体）
        if models and faults:
            m, fc = models[0], faults[0]
            return (
                f"MATCH (m:Model {{name: '{m}'}})-[:HAS_FAULT]->(f:Fault {{code: '{fc}'}})"
                f"-[:CAUSED_BY]->(c:Cause)-[:SOLVED_BY]->(s:Solution) "
                f"WHERE {act('m')} AND {act('f')} AND {act('c')} AND {act('s')} "
                f"OPTIONAL MATCH (s)-[:REQUIRES_FILTER]->(rf:Filter) "
                f"WHERE {act('rf')} "
                f"RETURN f.symptom AS symptom, c.description AS cause, "
                f"s.description AS solution, rf.code AS require_filter"
            )

        if faults and not models:
            # 故障代码 → 原因 + 方案
            code = faults[0]
            return (
                f"MATCH (f:Fault {{code: '{code}'}})-[:CAUSED_BY]->(c:Cause)-[:SOLVED_BY]->(s:Solution) "
                f"WHERE {act('f')} AND {act('c')} AND {act('s')} "
                f"OPTIONAL MATCH (s)-[:REQUIRES_FILTER]->(rf:Filter) "
                f"WHERE {act('rf')} "
                f"RETURN f.symptom AS symptom, c.description AS cause, s.description AS solution, "
                f"rf.code AS require_filter, rf.type AS require_filter_type"
            )

        if models and not faults:
            # 症状匹配：问句含症状文本 → 精确定位单个故障
            matched = find_faults_by_symptom(question) if question else []
            if matched:
                name, fc = models[0], matched[0]
                return (
                    f"MATCH (m:Model {{name: '{name}'}})-[:HAS_FAULT]->(f:Fault {{code: '{fc}'}})"
                    f"-[:CAUSED_BY]->(c:Cause)-[:SOLVED_BY]->(s:Solution) "
                    f"WHERE {act('m')} AND {act('f')} AND {act('c')} AND {act('s')} "
                    f"OPTIONAL MATCH (s)-[:REQUIRES_FILTER]->(rf:Filter) "
                    f"WHERE {act('rf')} "
                    f"RETURN f.symptom AS symptom, c.description AS cause, "
                    f"s.description AS solution, rf.code AS require_filter"
                )
            # 型号 → 故障 + 原因 + 方案 + 滤芯
            name = models[0]
            return (
                f"MATCH (m:Model {{name: '{name}'}})-[:HAS_FAULT]->(f:Fault)-[:CAUSED_BY]->(c:Cause)-[:SOLVED_BY]->(s:Solution) "
                f"WHERE {act('m')} AND {act('f')} AND {act('c')} AND {act('s')} "
                f"OPTIONAL MATCH (s)-[:REQUIRES_FILTER]->(rf:Filter) "
                f"WHERE {act('rf')} "
                f"RETURN f.code AS fault_code, f.symptom AS symptom, c.description AS cause, "
                f"s.description AS solution, s.cost AS cost, rf.code AS require_filter"
            )

    # --- 批次召回 ---
    if intent == "batch_recall":
        batches = all_list("Batch")
        customers = all_list("Customer")
        orders = all_list("Order")

        if batches and customers:
            bid, cid = batches[0], customers[0]
            return (
                f"MATCH (c:Customer {{id: '{cid}'}})-[:PLACED]->(o:Order)-[:FROM_BATCH]->(b:Batch {{id: '{bid}'}}) "
                f"WHERE {act('c')} AND {act('o')} AND {act('b')} "
                f"RETURN c.id AS customer_id, c.name AS customer_name, o.id AS order_id, o.status AS order_status, "
                f"b.recall_status AS recall_status"
            )

        if batches and not customers and not orders:
            bid = batches[0]
            # 问客户/订单影响 → 影响模板（优先于状态模板）
            if any(kw in question for kw in ("客户", "订单")):
                return (
                    f"MATCH (b:Batch {{id: '{bid}'}}) "
                    f"OPTIONAL MATCH (b)<-[:FROM_BATCH]-(o:Order)<-[:PLACED]-(c:Customer) "
                    f"WHERE {act('b')} AND (o IS NULL OR {act('o')}) AND (c IS NULL OR {act('c')}) "
                    f"OPTIONAL MATCH (b)-[:AFFECTS]->(f:Filter)<-[:REQUIRES_FILTER]-(s:Solution) "
                    f"RETURN b.id AS batch_id, b.recall_status AS recall_status, "
                    f"COLLECT(DISTINCT c.id) AS affected_customers, COLLECT(DISTINCT o.id) AS affected_orders, "
                    f"f.code AS affected_filter_code, s.description AS solution"
                )
            # 批次 → 召回状态
            if len(batches) == 1:
                return (
                    f"MATCH (b:Batch {{id: '{bid}'}}) "
                    f"WHERE {act('b')} "
                    f"OPTIONAL MATCH (b)-[:AFFECTS]->(f:Filter) "
                    f"OPTIONAL MATCH (b)-[:PRODUCES]->(m:Model) "
                    f"RETURN b.id AS batch_id, b.recall_status AS recall_status, "
                    f"f.code AS affected_filter, m.name AS produced_model"
                )

        if batches:
            bid = batches[0]
            # 批次 → 影响客户/订单/滤芯/方案
            return (
                f"MATCH (b:Batch {{id: '{bid}'}}) "
                f"WHERE {act('b')} "
                f"OPTIONAL MATCH (b)-[:AFFECTS]->(f:Filter) "
                f"OPTIONAL MATCH (b)<-[:FROM_BATCH]-(o:Order)<-[:PLACED]-(c:Customer) "
                f"OPTIONAL MATCH (f)<-[:REQUIRES_FILTER]-(s:Solution) "
                f"RETURN b.id AS batch_id, b.recall_status AS recall_status, "
                f"COLLECT(DISTINCT c.id) AS affected_customers, COLLECT(DISTINCT o.id) AS affected_orders, "
                f"f.code AS affected_filter_code, s.description AS solution"
            )

        # 仅型号 → 反查生产批次
        if all_list("Model"):
            name = all_list("Model")[0]
            return (
                f"MATCH (b:Batch)-[:PRODUCES]->(m:Model {{name: '{name}'}}) "
                f"WHERE {act('b')} AND {act('m')} "
                f"RETURN b.id AS batch_id, b.recall_status AS recall_status, m.name AS model_name"
            )

        if customers:
            cid = customers[0]
            return (
                f"MATCH (c:Customer {{id: '{cid}'}})-[:PLACED]->(o:Order)-[:FROM_BATCH]->(b:Batch) "
                f"WHERE {act('c')} AND {act('o')} AND {act('b')} "
                f"RETURN c.id AS customer_id, o.id AS order_id, o.status AS order_status, "
                f"b.id AS batch_id, b.recall_status AS recall_status"
            )

        if orders:
            oid = orders[0]
            return (
                f"MATCH (o:Order {{id: '{oid}'}})-[:CONTAINS]->(m:Model)-[:PRODUCES]-(b:Batch) "
                f"WHERE {act('o')} AND {act('m')} AND {act('b')} "
                f"OPTIONAL MATCH (o)-[:FROM_BATCH]->(b2:Batch) "
                f"RETURN o.id AS order_id, m.name AS model_name, b.id AS batch_id, b2.recall_status AS recall_status"
            )

        # 无实体 → 召回中批次清单
        return (
            f"MATCH (b:Batch {{recall_status: 'active'}}) "
            f"WHERE {act('b')} "
            f"RETURN b.id AS batch_id, b.recall_status AS recall_status"
        )

    # --- 通用：没匹配到特定模板 ---
    # 如果有 Model，查它的 USES + HAS_FAULT 关系
    if "Model" in entities:
        name = entities["Model"][0]
        return (
            f"MATCH (m:Model {{name: '{name}'}}) "
            f"WHERE {act('m')} "
            f"OPTIONAL MATCH (m)-[:USES]->(f:Filter) "
            f"OPTIONAL MATCH (m)-[:HAS_FAULT]->(flt:Fault) "
            f"RETURN m.name AS model_name, COLLECT(DISTINCT f.code) AS filters, "
            f"COLLECT(DISTINCT flt.symptom) AS faults"
        )

    return None  # 无法模板化，回退 LLM
