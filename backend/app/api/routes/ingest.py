# @Author: RebeccaZhou
# @Description: Data ingestion (ETL) API endpoints
#              数据接入（ETL）API：
"""
- GET  /ingest/template             下载 Excel 导入模板
- POST /ingest/validate             上传 Excel 只校验不入图
- POST /ingest/load                 上传 Excel 校验通过后增量入图
- GET  /ingest/state                最近批次水位线
- POST /ingest/extract              非结构化文本 LLM 抽取 → 审核队列
- GET  /ingest/review               审核队列列表 / counts
- POST /ingest/review/{id}/decision 审核通过（入图）/驳回（支持人工修正）
- GET  /ingest/dicts/status         实体动态词典状态
- POST /ingest/dicts/refresh        手动刷新词典
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from loguru import logger
from pydantic import BaseModel

from app.core.deps import get_neo4j_client
from app.graph.neo4j_client import Neo4jClient
from app.ingest.entity_dict import entity_dict
from app.ingest.extractor import DocExtractor, chunk_text
from app.ingest.loader import load_parsed, load_state
from app.ingest.review import review_store
from app.ingest.validator import validate_workbook
from app.ingest.workbook import generate_workbook
from app.llm.providers import LLMProvider

router = APIRouter()

@router.get("/template")
async def download_template():
    from fastapi.responses import Response

    data = generate_workbook()
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=purifiergraph_template.xlsx"},
    )

async def _read_upload(file: UploadFile) -> bytes:
    if not file.filename or not file.filename.lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(400, "请上传 .xlsx 文件")
    data = await file.read()
    if len(data) > 20 * 1024 * 1024:
        raise HTTPException(400, "文件超过 20MB")
    return data

@router.post("/validate")
async def validate(file: UploadFile = File(...)):
    data = await _read_upload(file)
    report, _ = validate_workbook(data)
    return {"filename": file.filename, **report.as_dict()}

@router.post("/load")
async def load(
    file: UploadFile = File(...),
    source: str = Form("excel"),
    retire_missing: bool = Form(False),
    client: Neo4jClient = Depends(get_neo4j_client),
):
    data = await _read_upload(file)
    report, parsed = validate_workbook(data)
    if not report.ok:
        raise HTTPException(422, detail={
            "message": "校验未通过，已阻止入图",
            **report.as_dict(),
        })
    result = await load_parsed(
        client, parsed, source=f"{source}:{file.filename}", retire_missing=retire_missing
    )
    # 数据变了，立即刷新实体词典
    try:
        await entity_dict.load_from_graph(client)
    except Exception as e:
        logger.warning(f"入图后词典刷新失败: {e}")
    return {"validation": report.as_dict(), "load": result}

@router.get("/state")
async def state():
    return load_state()

# ---------------- 非结构化抽取 ----------------

class ExtractReq(BaseModel):
    text: str
    source_doc: str = ""
    chunk_index: int = 0
    enqueue: bool = True

@router.post("/extract")
async def extract(req: ExtractReq):
    try:
        item = await DocExtractor().extract_text(
            req.text,
            source_doc=req.source_doc,
            chunk_index=req.chunk_index,
            enqueue=req.enqueue,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return item

class ExtractBatchReq(BaseModel):
    text: str
    source_doc: str = ""
    max_chars: int = 1200

@router.post("/extract-batch")
async def extract_batch(req: ExtractBatchReq):
    """长文本切块后逐块抽取，入审核队列，返回入队条目摘要。"""
    chunks = chunk_text(req.text, max_chars=req.max_chars)
    extractor = DocExtractor()
    queued = []
    for i, chunk in enumerate(chunks):
        item = await extractor.extract_text(
            chunk, source_doc=req.source_doc, chunk_index=i
        )
        queued.append({"id": item["id"], "chunk_index": i,
                       "entities": _count_entities(item),
                       "relations": len(item.get("relations", []))})
    return {"chunks": len(chunks), "queued": queued}

def _count_entities(item: dict) -> dict[str, int]:
    return {label: len(rows) for label, rows in item.get("entities", {}).items()}

# ---------------- 审核工作台 ----------------

@router.get("/review/counts")
async def review_counts():
    return review_store.counts()

@router.get("/review")
async def review_list(status: str = "pending", limit: int = 200):
    return review_store.list_items(status=status, limit=limit)

@router.get("/review/{item_id}")
async def review_detail(item_id: str):
    item = review_store.get(item_id)
    if not item:
        raise HTTPException(404, "审核记录不存在")
    return item

class DecisionReq(BaseModel):
    action: str               # approve / reject
    comment: str = ""
    edits: dict | None = None

@router.post("/review/{item_id}/decision")
async def review_decision(
    item_id: str,
    req: DecisionReq,
    client: Neo4jClient = Depends(get_neo4j_client),
):
    try:
        item = await review_store.decide(
            client, item_id, req.action, req.comment, req.edits
        )
    except KeyError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(409, str(e))
    # approve 后词典可能出现新编码，异步刷新
    if req.action == "approve":
        try:
            await entity_dict.load_from_graph(client)
        except Exception as e:
            logger.warning(f"审核入图后词典刷新失败: {e}")
    return item

# ---------------- 动态实体词典 ----------------

@router.get("/dicts/status")
async def dicts_status():
    return entity_dict.status()

@router.post("/dicts/refresh")
async def dicts_refresh(client: Neo4jClient = Depends(get_neo4j_client)):
    total = await entity_dict.load_from_graph(client)
    return {"ok": True, "code_count": total, **entity_dict.status()}
