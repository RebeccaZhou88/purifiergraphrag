# @Author: RebeccaZhou
# @Description: FastAPI dependency injection: Neo4j / Kernel / Bus singletons
#              FastAPI 依赖注入：Neo4j / Kernel / Bus 单例。
from __future__ import annotations

from functools import lru_cache

from .config import settings

@lru_cache
def get_neo4j_client():
    from app.graph.neo4j_client import Neo4jClient

    return Neo4jClient(
        uri=settings.neo4j_uri,
        user=settings.neo4j_user,
        password=settings.neo4j_password,
    )

@lru_cache
def get_kernel():
    from app.kernel.kernel import build_kernel

    return build_kernel()

def get_settings_dep():
    return settings
