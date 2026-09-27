# @Author: RebeccaZhou
# @Description: Health check and service metadata
#              健康检查与元信息。
from fastapi import APIRouter

from app.core.config import settings

router = APIRouter()

@router.get("/health")
async def health():
    return {"status": "ok", "provider": settings.llm_provider, "model": settings.llm_model()}

@router.get("/models")
async def list_models():
    """供前端模型下拉（默认第一项）。"""
    return {"models": settings.available_models, "default": settings.available_models[0]["id"]}
