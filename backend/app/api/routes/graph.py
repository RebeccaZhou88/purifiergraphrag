# @Author: RebeccaZhou
# @Description: Graph query/visualization route: returns nodes and relationships for GraphView
#              图谱查询/可视化路由：返回节点 + 关系，供前端 GraphView 渲染。
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.core.deps import get_neo4j_client
from app.graph.neo4j_client import Neo4jClient
from app.graph.schema import schema_view

router = APIRouter()

@router.get("/graph/schema")
async def get_schema():
    return schema_view()

@router.get("/graph")
async def get_graph(
    label: str | None = Query(None, description="按节点标签过滤"),
    limit: int = Query(200, ge=1, le=500),
    neo4j: Neo4jClient = Depends(get_neo4j_client),
):
    """返回节点 + 关系（限制规模）。"""
    if label:
        node_cypher = f"MATCH (n:{label}) RETURN id(n) AS id, labels(n) AS labels, properties(n) AS props LIMIT $limit"
        rel_cypher = (
            f"MATCH (a:{label})-[r]->(b) "
            "RETURN id(a) AS src, id(b) AS dst, type(r) AS type LIMIT $limit"
        )
    else:
        node_cypher = "MATCH (n) WHERE size(labels(n)) > 0 RETURN id(n) AS id, labels(n) AS labels, properties(n) AS props LIMIT $limit"
        rel_cypher = "MATCH (a)-[r]->(b) RETURN id(a) AS src, id(b) AS dst, type(r) AS type LIMIT $limit"

    nodes = await neo4j.run(node_cypher, {"limit": limit})
    edges = await neo4j.run(rel_cypher, {"limit": limit})

    return {
        "nodes": [
            {
                "id": str(n["id"]),
                "label": (n["labels"] or ["Node"])[0],
                "properties": {k: v for k, v in n["props"].items() if k not in ("name", "code", "id")} or n["props"],
                "title": n["props"].get("name") or n["props"].get("code") or n["props"].get("id"),
            }
            for n in nodes
        ],
        "edges": [
            {"source": str(e["src"]), "target": str(e["dst"]), "type": e["type"]}
            for e in edges
        ],
    }
