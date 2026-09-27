# @Author: RebeccaZhou
# @Description: Knowledge graph schema: constraints, indexes and relationships
#              知识图谱 Schema：约束、索引、关系定义。
"""

实体 8 类：Model/Filter/Fault/Cause/Solution/Customer/Order/Batch
关系见 RELATIONSHIPS 列表（供前端 GraphView 展示）。
"""
from __future__ import annotations

from typing import Any

from loguru import logger

from .neo4j_client import Neo4jClient

# 节点标签
NODE_LABELS = ["Model", "Filter", "Fault", "Cause", "Solution", "Customer", "Order", "Batch"]

# 关系类型 (源, 关系, 目标, 描述)
RELATIONSHIPS: list[tuple[str, str, str, str]] = [
    ("Model", "USES", "Filter", "型号使用滤芯"),
    ("Model", "HAS_FAULT", "Fault", "型号存在故障"),
    ("Fault", "CAUSED_BY", "Cause", "故障由原因导致"),
    ("Cause", "SOLVED_BY", "Solution", "原因由方案解决"),
    ("Solution", "REQUIRES_FILTER", "Filter", "方案需更换滤芯"),
    ("Customer", "PLACED", "Order", "客户下单"),
    ("Order", "CONTAINS", "Model", "订单包含型号"),
    ("Order", "FROM_BATCH", "Batch", "订单来自批次"),
    ("Batch", "PRODUCES", "Model", "批次生产型号"),
    ("Batch", "AFFECTS", "Filter", "批次影响滤芯"),
]

# 唯一性约束（同时建索引）
CONSTRAINTS = [
    "CREATE CONSTRAINT model_name IF NOT EXISTS FOR (n:Model) REQUIRE n.name IS UNIQUE",
    "CREATE CONSTRAINT filter_code IF NOT EXISTS FOR (n:Filter) REQUIRE n.code IS UNIQUE",
    "CREATE CONSTRAINT fault_code IF NOT EXISTS FOR (n:Fault) REQUIRE n.code IS UNIQUE",
    "CREATE CONSTRAINT cause_id IF NOT EXISTS FOR (n:Cause) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT solution_id IF NOT EXISTS FOR (n:Solution) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT customer_id IF NOT EXISTS FOR (n:Customer) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT order_id IF NOT EXISTS FOR (n:Order) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT batch_id IF NOT EXISTS FOR (n:Batch) REQUIRE n.id IS UNIQUE",
]

# 辅助索引（多跳查询性能）
INDEXES = [
    "CREATE INDEX model_series IF NOT EXISTS FOR (n:Model) ON (n.series)",
    "CREATE INDEX filter_type IF NOT EXISTS FOR (n:Filter) ON (n.type)",
    "CREATE INDEX batch_recall IF NOT EXISTS FOR (n:Batch) ON (n.recall_status)",
    "CREATE INDEX order_status IF NOT EXISTS FOR (n:Order) ON (n.status)",
    "CREATE INDEX customer_region IF NOT EXISTS FOR (n:Customer) ON (n.region)",
]

async def ensure_schema(client: Neo4jClient) -> None:
    """建约束与索引。"""
    for stmt in CONSTRAINTS + INDEXES:
        try:
            await client.write(stmt)
        except Exception as e:
            logger.warning(f"Schema 语句执行失败（可能已存在）: {stmt} -> {e}")
    logger.info(f"Schema 就绪: {len(CONSTRAINTS)} 约束 / {len(INDEXES)} 索引")

def schema_view() -> dict[str, Any]:
    """供前端展示的 Schema 元数据。"""
    return {
        "nodes": NODE_LABELS,
        "relationships": [
            {"source": s, "type": t, "target": d, "desc": desc}
            for s, t, d, desc in RELATIONSHIPS
        ],
    }
