# @Author: RebeccaZhou
# @Description: Manual review queue: LLM extraction results await expert approve/reject before graph loading
#              人工审核队列：LLM 抽取结果先进队列，业务专家 approve / reject 后才入图。
"""

持久化：data/ingest/review_queue.jsonl（每行一条记录，追加写，简单可靠，
POC/中小数据量足够；生产可平滑换成 SQLite/PostgreSQL）。

记录契约：
{
  "id": "RV-20260924-000001",
  "status": "pending|approved|rejected",
  "source_doc": "2024售后维修手册.pdf",
  "chunk_index": 3,
  "text": "原文片段（审核依据）",
  "entities": {"Fault": [{"temp_id":"new_1","code":null,"symptom":"...","confidence":0.9}], ...},
  "relations": [{"type":"CAUSED_BY","from":"FLT-001","to":"!temp:new_2",
                 "evidence":"...","confidence":0.8}],
  "notes": "...",
  "created_at": "...", "reviewed_at": "...", "comment": "...",
  "load_result": null
}
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from loguru import logger

from ..graph.neo4j_client import Neo4jClient
from .loader import load_extracted_item

_QUEUE_DIR = Path(__file__).resolve().parents[2] / "data" / "ingest"
_QUEUE_FILE = _QUEUE_DIR / "review_queue.jsonl"

class ReviewStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or _QUEUE_FILE

    # ---------- 基础读写 ----------

    def _read_all(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        items = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                items.append(json.loads(line))
            except json.JSONDecodeError:
                logger.warning(f"审核队列跳过坏行: {line[:80]}")
        return items

    def _write_all(self, items: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(
            "\n".join(json.dumps(i, ensure_ascii=False) for i in items) + "\n",
            encoding="utf-8",
        )
        tmp.replace(self.path)

    # ---------- 队列操作 ----------

    def add(
        self,
        extracted: dict[str, Any],
        *,
        text: str,
        source_doc: str = "",
        chunk_index: int = 0,
    ) -> dict[str, Any]:
        items = self._read_all()
        seq = len(items) + 1
        item = {
            "id": f"RV-{time.strftime('%Y%m%d')}-{seq:06d}",
            "status": "pending",
            "source_doc": source_doc,
            "chunk_index": chunk_index,
            "text": text[:2000],
            "entities": extracted.get("entities", {}),
            "relations": extracted.get("relations", []),
            "notes": extracted.get("notes", ""),
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "reviewed_at": None,
            "comment": "",
            "load_result": None,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
        return item

    def list_items(self, status: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        items = self._read_all()
        if status and status != "all":
            items = [i for i in items if i["status"] == status]
        items.reverse()  # 最新的在前
        return items[:limit]

    def counts(self) -> dict[str, int]:
        c = {"pending": 0, "approved": 0, "rejected": 0}
        for i in self._read_all():
            c[i["status"]] = c.get(i["status"], 0) + 1
        c["total"] = sum(c.values())
        return c

    def get(self, item_id: str) -> dict[str, Any] | None:
        return next((i for i in self._read_all() if i["id"] == item_id), None)

    async def decide(
        self,
        client: Neo4jClient,
        item_id: str,
        action: str,
        comment: str = "",
        edits: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """审核决定。

        action: approve（入图）/ reject（驳回）
        edits:  审核员在页面上对抽取结果的人工修正（可选），形如
                {"entities": {...}, "relations": [...]}，整体替换对应字段
        """
        if action not in ("approve", "reject"):
            raise ValueError("action 只能是 approve / reject")
        items = self._read_all()
        target = next((i for i in items if i["id"] == item_id), None)
        if target is None:
            raise KeyError(f"审核记录不存在: {item_id}")
        if target["status"] != "pending":
            raise ValueError(f"该记录已审核: {target['status']}")

        if edits:
            if edits.get("entities"):
                target["entities"] = edits["entities"]
            if edits.get("relations"):
                target["relations"] = edits["relations"]

        target["status"] = "approved" if action == "approve" else "rejected"
        target["reviewed_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        target["comment"] = comment

        if action == "approve":
            result = await load_extracted_item(client, target)
            target["load_result"] = result
        self._write_all(items)
        return target

# 进程级单例
review_store = ReviewStore()
