# @Author: RebeccaZhou
# @Description: Unstructured document extractor: text-> LLM triple extraction per schema -> review queue
#              非结构化文档抽取器：文本 → LLM 按 Schema 抽三元组 → 审核队列。
"""

典型用法：
    extractor = DocExtractor(llm)
    item = await extractor.extract_text(open("manual.txt").read(), source_doc="manual.txt")
    # item 已入审核队列，业务专家在工作台确认后才真正写图

批量文档建议先按段落/标题切成 500~1500 字的 chunk 再逐块抽取（见 CLI）。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from loguru import logger

from ..llm.providers import LLMProvider
from .entity_dict import entity_dict
from .prompts import EXTRACT_SYSTEM, build_codebook, extract_user, safe_parse_json
from .registry import NODE_SPECS
from .review import review_store

_SEED_DIR = Path(__file__).resolve().parents[2] / "data" / "seed"

def _label_to_file(label: str) -> str:
    return {"Model": "models", "Filter": "filters", "Fault": "faults",
            "Cause": "causes", "Solution": "solutions", "Customer": "customers",
            "Order": "orders", "Batch": "batches"}[label]

_SEED_FILE_BY_LABEL = {s.label: f"{_label_to_file(s.label)}.json" for s in NODE_SPECS}

def build_seed_fallback_codebook() -> dict[str, list[str]]:
    """动态词典未就绪时，从 seed JSON 读编码兜底。"""
    out: dict[str, list[str]] = {}
    for spec in NODE_SPECS:
        f = _SEED_DIR / _SEED_FILE_BY_LABEL[spec.label]
        if not f.exists():
            continue
        try:
            rows = json.loads(f.read_text(encoding="utf-8"))
            out[spec.label] = [str(r[spec.pk]) for r in rows if spec.pk in r]
        except (OSError, ValueError, KeyError):
            pass
    return out

class DocExtractor:
    def __init__(self, llm: LLMProvider | None = None) -> None:
        self._llm = llm or LLMProvider()

    def _codebook_text(self) -> str:
        if entity_dict.is_ready():
            codes_by_label = {
                s.label: entity_dict.codes(s.label)
                for s in NODE_SPECS
                if entity_dict.codes(s.label)
            }
        else:
            codes_by_label = build_seed_fallback_codebook()
        return build_codebook(codes_by_label)

    async def extract_text(
        self,
        text: str,
        *,
        source_doc: str = "",
        chunk_index: int = 0,
        enqueue: bool = True,
    ) -> dict[str, Any]:
        """抽取单块文本。enqueue=True 时自动写入审核队列。"""
        if not text or not text.strip():
            raise ValueError("待抽取文本为空")

        codebook = self._codebook_text()
        raw = await self._llm.chat(
            EXTRACT_SYSTEM,
            extract_user(text, codebook, source_doc),
            temperature=0.0,
        )
        parsed = safe_parse_json(raw)
        parsed = self._normalize(parsed)

        if enqueue:
            return review_store.add(
                parsed, text=text, source_doc=source_doc, chunk_index=chunk_index
            )
        return parsed

    def _normalize(self, parsed: dict[str, Any]) -> dict[str, Any]:
        """清洗模型输出：只保留白名单字段/关系，补 confidence 默认值。"""
        allowed_labels = {s.label for s in NODE_SPECS}
        allowed_rels = {
            ("Model", "HAS_FAULT", "Fault"),
            ("Fault", "CAUSED_BY", "Cause"),
            ("Cause", "SOLVED_BY", "Solution"),
            ("Solution", "REQUIRES_FILTER", "Filter"),
            ("Model", "USES", "Filter"),
        }
        ents: dict[str, list[dict]] = {}
        for label, rows in (parsed.get("entities") or {}).items():
            if label not in allowed_labels or not isinstance(rows, list):
                continue
            spec = next(s for s in NODE_SPECS if s.label == label)
            clean_rows = []
            for r in rows:
                if not isinstance(r, dict):
                    continue
                clean = {f.key: r.get(f.key) for f in spec.fields if f.key in r}
                clean["temp_id"] = str(r.get("temp_id") or "").strip()
                clean["code"] = str(r.get("code") or "").strip() or None
                try:
                    clean["confidence"] = float(r.get("confidence", 0.5))
                except (TypeError, ValueError):
                    clean["confidence"] = 0.5
                clean_rows.append(clean)
            if clean_rows:
                ents[label] = clean_rows

        rels: list[dict] = []
        for r in parsed.get("relations") or []:
            if not isinstance(r, dict):
                continue
            key = (r.get("from_label"), r.get("type"), r.get("to_label"))
            if key not in allowed_rels:
                logger.info(f"抽取结果丢弃非白名单关系: {key}")
                continue
            rels.append({
                "type": r["type"],
                "from_label": r["from_label"], "from": str(r.get("from", "")),
                "to_label": r["to_label"], "to": str(r.get("to", "")),
                "evidence": str(r.get("evidence", ""))[:120],
                "confidence": _safe_float(r.get("confidence")),
            })
        return {"entities": ents, "relations": rels, "notes": str(parsed.get("notes", ""))}

def _safe_float(v: Any) -> float:
    try:
        return max(0.0, min(1.0, float(v)))
    except (TypeError, ValueError):
        return 0.5

def chunk_text(text: str, max_chars: int = 1200, overlap: int = 100) -> list[str]:
    """按字符长度切块（中文文档够用；生产可换语义切分/按标题切分）。"""
    text = text.strip()
    if len(text) <= max_chars:
        return [text] if text else []
    chunks, start = [], 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        # 尽量在换行处断开
        if end < len(text):
            nl = text.rfind("\n", start + max_chars // 2, end)
            if nl > start:
                end = nl + 1
        chunks.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return [c for c in chunks if c]
