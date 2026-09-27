# @Author: RebeccaZhou
# @Description: Pydantic DTOs: request/response models / Pydantic DTO
#              ：请求/响应模型。
"""

Pydantic DTO：请求/响应模型。
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ChatRequest(BaseModel):
    question: str
    model: str | None = None  # provider id：qwen/deepseek/azure_openai


class EvalRequest(BaseModel):
    model: str | None = None
    scenario: str | None = None  # 可选筛选场景


class GraphNode(BaseModel):
    id: str
    label: str
    properties: dict[str, Any]


class GraphEdge(BaseModel):
    source: str
    target: str
    type: str


class GraphData(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]


class EvalCaseResult(BaseModel):
    case_id: str
    scenario: str
    question: str
    expected: str
    answer: str
    passed: bool
    latency_ms: int
    rank: int  # 按准确率/速度排名
