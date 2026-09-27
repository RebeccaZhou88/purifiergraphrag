# @Author: RebeccaZhou
# @Description: FastAPI application entry: CORS, router mounting, seed import on startup
#              FastAPI 入口：CORS + 路由挂载 + 启动时种子数据导入。
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from app.api.routes import chat, eval as eval_route, graph, health, ingest
from app.core.config import settings

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("PurifierGraph backend 启动中...")
    if settings.seed_on_startup:
        try:
            from app.graph.neo4j_client import Neo4jClient
            from app.graph.schema import ensure_schema
            from app.graph.seed import seed_database

            client = Neo4jClient(
                uri=settings.neo4j_uri,
                user=settings.neo4j_user,
                password=settings.neo4j_password,
            )
            await ensure_schema(client)
            await seed_database(client)
            logger.info("Neo4j Schema 与种子数据就绪")
            # 从图谱加载实体编码动态词典（失败则规则引擎自动回退内置正则）
            from app.ingest.entity_dict import entity_dict

            await entity_dict.load_from_graph(client)
        except Exception as e:  # 启动失败不阻断，避免 Neo4j 未起时后端起不来
            logger.warning(f"种子数据导入失败（不影响启动）：{e}")
    yield
    logger.info("PurifierGraph backend 关闭")

app = FastAPI(title="PurifierGraph API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/api", tags=["health"])
app.include_router(chat.router, prefix="/api", tags=["chat"])
app.include_router(graph.router, prefix="/api", tags=["graph"])
app.include_router(eval_route.router, prefix="/api", tags=["eval"])
app.include_router(ingest.router, prefix="/api/ingest", tags=["ingest"])

@app.get("/")
async def root():
    return {"name": "PurifierGraph", "status": "ok", "docs": "/docs"}
