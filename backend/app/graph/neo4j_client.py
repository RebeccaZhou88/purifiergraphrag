# @Author: RebeccaZhou
# @Description: Async Neo4j client wrapper
#              Neo4j 异步客户端封装。
from __future__ import annotations

from typing import Any

from loguru import logger
from neo4j import AsyncGraphDatabase

class Neo4jClient:
    def __init__(self, uri: str, user: str, password: str) -> None:
        self._driver = AsyncGraphDatabase.driver(uri, auth=(user, password))

    async def close(self) -> None:
        await self._driver.close()

    async def run(self, query: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """执行查询并返回记录列表（每条记录转为 dict）。"""
        async with self._driver.session() as session:
            result = await session.run(query, params or {})
            records = [r.data() async for r in result]
            return records

    async def write(self, query: str, params: dict[str, Any] | None = None) -> None:
        """执行写操作（CREATE/MERGE）。"""
        async with self._driver.session() as session:
            await session.run(query, params or {})

    async def write_many(self, query: str, rows: list[dict[str, Any]]) -> None:
        """批量写入，使用 UNWIND。"""
        if not rows:
            return
        async with self._driver.session() as session:
            await session.run(query, {"rows": rows})

    async def ping(self) -> bool:
        try:
            await self.run("RETURN 1 AS ok")
            return True
        except Exception as e:
            logger.warning(f"Neo4j ping 失败: {e}")
            return False
