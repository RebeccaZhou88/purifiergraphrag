# @Author: RebeccaZhou
# @Description: Incremental graph loader: MERGE upsert + batch watermark + soft delete + dangling-edge validation
#              增量入图加载器：MERGE upsert + 批次水位线 + 软删除 + 悬空边图上校验。
"""

与 seed.py 的区别：
- seed.py：全量演示数据，读 data/seed/*.json，无来源/批次概念
- loader：面向客户回收文件，打来源标签（_source/_batch_id/_updated_at），
  可统计新增/更新，可软删除"本次没再出现"的实体，edges 入图前做图上校验

水位线文件：data/ingest/state.json（记录每次批次）
"""
from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger

from ..graph.neo4j_client import Neo4jClient
from .registry import NODE_SPECS, PK_BY_LABEL, REL_BY_TYPE

_STATE_DIR = Path(__file__).resolve().parents[2] / "data" / "ingest"
_STATE_FILE = _STATE_DIR / "state.json"

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def _coerce(value: Any, ftype: str) -> Any:
    if value == "" or value is None:
        return None
    if ftype == "int":
        return int(float(value))
    if ftype == "float":
        return float(value)
    return str(value)

async def _existing_pks(client: Neo4jClient, label: str, pk: str) -> set[str]:
    rows = await client.run(
        f"MATCH (n:{label}) WHERE n.{pk} IS NOT NULL RETURN n.{pk} AS pk"
    )
    return {str(r["pk"]) for r in rows}

async def load_parsed(
    client: Neo4jClient,
    parsed: dict[str, list[dict[str, Any]]],
    *,
    source: str = "excel",
    batch_id: str | None = None,
    retire_missing: bool = False,
) -> dict[str, Any]:
    """把 validator 解析过的数据增量写入图谱。

    Returns: 批次报告 {batch_id, created, updated, retired, edges_merged, orphan_edges}
    """
    batch_id = batch_id or f"B{int(time.time())}-{uuid.uuid4().hex[:6]}"
    ts = _now_iso()
    created: dict[str, int] = {}
    updated: dict[str, int] = {}
    retired: dict[str, int] = {}

    # ---------- 节点 ----------
    for spec in NODE_SPECS:
        rows = parsed.get(spec.label)
        if not rows:
            continue
        exist = await _existing_pks(client, spec.label, spec.pk)

        clean: list[dict[str, Any]] = []
        for rec in rows:
            row: dict[str, Any] = {}
            for fspec in spec.fields:
                v = _coerce(rec.get(fspec.key), fspec.ftype)
                if v is not None:  # 空值不覆盖已有属性
                    row[fspec.key] = v
            if spec.pk not in row:
                continue  # 理论上 validator 已挡
            row["_source"] = source
            row["_batch_id"] = batch_id
            row["_updated_at"] = ts
            # 生命周期标记独立命名，避开 Order.status（completed/pending）业务字段
            row["_lifecycle"] = "active"
            clean.append(row)

        if not clean:
            continue

        props = [f.key for fspec in [spec] for f in fspec.fields]
        # 内部审计字段也要 SET
        props_all = props + ["_source", "_batch_id", "_updated_at", "_lifecycle"]
        set_clause = ", ".join(f"n.{p} = row.{p}" for p in props_all)
        cypher = (
            f"UNWIND $rows AS row "
            f"MERGE (n:{spec.label} {{{spec.pk}: row.{spec.pk}}}) "
            f"SET {set_clause}"
        )
        await client.write_many(cypher, clean)

        new_pks = {str(r[spec.pk]) for r in clean}
        created[spec.label] = len(new_pks - exist)
        updated[spec.label] = len(new_pks & exist)
        logger.info(f"[{batch_id}] {spec.label}: +{created[spec.label]} ~{updated[spec.label]}")

        # 软删除：同源但本次没出现的实体 → _lifecycle=inactive（保留节点，不物理删）
        if retire_missing:
            res = await client.run(
                f"MATCH (n:{spec.label}) "
                f"WHERE n._source = $source AND n._lifecycle <> 'inactive' "
                f"AND (n._batch_id IS NULL OR n._batch_id <> $batch_id) "
                f"SET n._lifecycle = 'inactive', n._updated_at = $ts "
                f"RETURN count(n) AS c",
                {"source": source, "batch_id": batch_id, "ts": ts},
            )
            retired[spec.label] = res[0]["c"] if res else 0

    # ---------- 关系（图上二次校验端点） ----------
    edges = parsed.get("__edges__", [])
    graph_index: dict[str, set[str]] = {}
    labels_needed = {lab for e in edges for lab in (
        REL_BY_TYPE[e["type"]].source, REL_BY_TYPE[e["type"]].target
    ) if e["type"] in REL_BY_TYPE}
    for label in labels_needed:
        graph_index[label] = await _existing_pks(client, label, PK_BY_LABEL[label])

    orphan: list[dict[str, str]] = []
    by_type: dict[str, list[dict[str, str]]] = {}
    for e in edges:
        rel = REL_BY_TYPE.get(e["type"])
        if rel is None:
            orphan.append({**e, "reason": "未知关系类型"})
            continue
        if e["from"] not in graph_index[rel.source]:
            orphan.append({**e, "reason": f"源端点 {e['from']} 不是 {rel.source}"})
            continue
        if e["to"] not in graph_index[rel.target]:
            orphan.append({**e, "reason": f"目标端点 {e['to']} 不是 {rel.target}"})
            continue
        by_type.setdefault(e["type"], []).append(e)

    edges_merged = 0
    for rtype, rows in by_type.items():
        rel = REL_BY_TYPE[rtype]
        cypher = (
            "UNWIND $rows AS row "
            f"MATCH (a:{rel.source} {{{PK_BY_LABEL[rel.source]}: row.from}}) "
            f"MATCH (b:{rel.target} {{{PK_BY_LABEL[rel.target]}: row.to}}) "
            f"MERGE (a)-[:{rtype}]->(b)"
        )
        await client.write_many(cypher, rows)
        edges_merged += len(rows)

    report = {
        "batch_id": batch_id,
        "source": source,
        "finished_at": ts,
        "created": created,
        "updated": updated,
        "retired": retired,
        "edges_merged": edges_merged,
        "orphan_edges": orphan,
    }
    _append_state(report)
    return report

# ============================================================
# 审核通过的抽取记录入图（新实体自动分配编码）
# ============================================================

async def load_extracted_item(client: Neo4jClient, item: dict[str, Any]) -> dict[str, Any]:
    """把人工审核通过的 LLM 抽取记录写入图。

    item 契约见 review.py。entities 中主键为空的新实体按序列分配编码：
    FLT/CS/SL 前缀 + 三位序号；带 code 的（模型/滤芯等引用）直接复用。
    """
    ts = _now_iso()
    source = f"doc:{item.get('source_doc', 'unknown')}"
    id_map: dict[str, str] = {}   # temp_id → 实际编码

    prefix_by_label = {"Fault": "FLT", "Cause": "CS", "Solution": "SL"}
    for label, ents in item.get("entities", {}).items():
        spec = next((s for s in NODE_SPECS if s.label == label), None)
        if spec is None:
            continue
        rows_out: list[dict[str, Any]] = []
        for ent in ents:
            code = (ent.get("code") or "").strip()
            temp = ent.get("temp_id") or ""
            if code:
                final = code
            else:
                prefix = prefix_by_label.get(label, label[:3].upper())
                final = await _next_code(client, label, spec.pk, prefix)
            if temp:
                id_map[temp] = final
            row = {spec.pk: final, "_source": source,
                   "_updated_at": ts, "_lifecycle": "active"}
            for fspec in spec.fields:
                if fspec.key == spec.pk:
                    continue
                v = ent.get(fspec.key)
                if v not in (None, ""):
                    row[fspec.key] = _coerce(v, fspec.ftype)
            rows_out.append(row)
        if rows_out:
            keys = set().union(*(r.keys() for r in rows_out)) - {spec.pk}
            set_clause = ", ".join(f"n.{k} = row.{k}" for k in keys)
            cypher = (
                f"UNWIND $rows AS row MERGE (n:{spec.label} {{{spec.pk}: row.{spec.pk}}})"
                + (f" SET {set_clause}" if set_clause else "")
            )
            await client.write_many(cypher, rows_out)

    # 关系：把 !temp:xxx 形式的端点引用解析成实际编码
    merged, skipped = 0, []
    for e in item.get("relations", []):
        rel = REL_BY_TYPE.get(e.get("type", ""))
        if not rel:
            skipped.append({**e, "reason": "未知关系类型"})
            continue
        a = _resolve_ref(e.get("from"), id_map)
        b = _resolve_ref(e.get("to"), id_map)
        if not a or not b:
            skipped.append({**e, "reason": "端点引用无法解析"})
            continue
        # rtype 不能参数化，但值来自白名单 REL_SPECS，无注入风险
        await client.write(
            f"MATCH (x:{rel.source} {{{PK_BY_LABEL[rel.source]}: $a}}) "
            f"MATCH (y:{rel.target} {{{PK_BY_LABEL[rel.target]}: $b}}) "
            f"MERGE (x)-[:{rel.rtype}]->(y)",
            {"a": a, "b": b},
        )
        merged += 1

    return {"id_map": id_map, "edges_merged": merged, "skipped": skipped}

async def _next_code(client: Neo4jClient, label: str, pk: str, prefix: str) -> str:
    rows = await client.run(
        f"MATCH (n:{label}) WHERE n.{pk} STARTS WITH $p RETURN n.{pk} AS c",
        {"p": prefix + "-"},
    )
    max_n = 0
    for r in rows:
        tail = str(r["c"])[len(prefix) + 1:]
        if tail.isdigit():
            max_n = max(max_n, int(tail))
    return f"{prefix}-{max_n + 1:03d}"

def _resolve_ref(ref: Any, id_map: dict[str, str]) -> str:
    s = str(ref or "").strip()
    if s.startswith("!temp:"):
        return id_map.get(s[6:], "")
    return s

# ============================================================
# 批次水位线
# ============================================================

def _append_state(report: dict[str, Any]) -> None:
    try:
        _STATE_DIR.mkdir(parents=True, exist_ok=True)
        history = []
        if _STATE_FILE.exists():
            history = json.loads(_STATE_FILE.read_text(encoding="utf-8")).get("runs", [])
        history.append(report)
        history = history[-100:]  # 只留最近 100 批
        _STATE_FILE.write_text(
            json.dumps({"runs": history}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError as e:
        logger.warning(f"水位线写入失败（不影响入图）: {e}")

def load_state() -> dict[str, Any]:
    if not _STATE_FILE.exists():
        return {"runs": []}
    return json.loads(_STATE_FILE.read_text(encoding="utf-8"))
