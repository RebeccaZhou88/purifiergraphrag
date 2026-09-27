# @Author: RebeccaZhou
# @Description: Seed data loader: reads data/seed/*.json and MERGEs nodes/relationships, idempotent
#              种子数据导入：读取 data/seed/*.json，MERGE 节点与关系。幂等。
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from loguru import logger

from .neo4j_client import Neo4jClient

SEED_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "seed"

# (文件名, 标签, 主键字段)
NODE_FILES = [
    ("models.json", "Model", "name"),
    ("filters.json", "Filter", "code"),
    ("faults.json", "Fault", "code"),
    ("causes.json", "Cause", "id"),
    ("solutions.json", "Solution", "id"),
    ("customers.json", "Customer", "id"),
    ("batches.json", "Batch", "id"),
]

def _load(name: str) -> list[dict[str, Any]]:
    path = SEED_DIR / name
    if not path.exists():
        logger.warning(f"种子文件不存在: {path}")
        return []
    return json.loads(path.read_text(encoding="utf-8"))

async def seed_database(client: Neo4jClient) -> None:
    """幂等导入节点 + 关系。"""
    # 1. 节点
    for fname, label, pk in NODE_FILES:
        rows = _load(fname)
        if not rows:
            continue
        props = list(rows[0].keys())
        set_clause = ", ".join(f"n.{p} = row.{p}" for p in props)
        cypher = (
            f"UNWIND $rows AS row "
            f"MERGE (n:{label} {{{pk}: row.{pk}}}) "
            f"SET {set_clause}"
        )
        await client.write_many(cypher, rows)
        logger.info(f"导入 {label}: {len(rows)} 条")

    # 2. 订单节点（剥离外键字段 customer_id/model/batch_id）
    orders = _load("orders.json")
    order_rows = [{"id": o["id"], "date": o["date"], "status": o["status"]} for o in orders]
    if order_rows:
        cypher = (
            "UNWIND $rows AS row "
            "MERGE (n:Order {id: row.id}) "
            "SET n.date = row.date, n.status = row.status"
        )
        await client.write_many(cypher, order_rows)
        logger.info(f"导入 Order: {len(order_rows)} 条")

    # 3. 关系（按类型分组，因为关系类型不能参数化）
    edges = _load("edges.json")
    if edges:
        rels_by_type: dict[str, list[dict[str, Any]]] = {}
        for e in edges:
            rels_by_type.setdefault(e["type"], []).append(e)
        for rtype, rows in rels_by_type.items():
            cypher = _rel_cypher(rtype, rows[0])
            await client.write_many(cypher, rows)
        logger.info(f"导入关系: {len(edges)} 条 / {len(rels_by_type)} 类型")

    logger.info("种子数据导入完成")

def _rel_cypher(rel_type: str, sample: dict[str, Any]) -> str:
    """按关系类型生成 UNWIND Cypher。"""
    fl, fk = sample["from_label"], sample["from_key"]
    tl, tk = sample["to_label"], sample["to_key"]
    return (
        f"UNWIND $rows AS row "
        f"MATCH (a:{fl} {{{fk}: row.from}}) "
        f"MATCH (b:{tl} {{{tk}: row.to}}) "
        f"MERGE (a)-[:{rel_type}]->(b)"
    )
