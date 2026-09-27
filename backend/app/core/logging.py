# @Author: RebeccaZhou
# @Description: Structured logging and step event bus
#              结构化日志 + 步骤事件总线。
"""

步骤事件总线供 SSE 实时推送 SK 各 Plugin 调用与检索过程日志，
满足"实时终端输出详细关键信息"的用户偏好。
"""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from loguru import logger

from .config import settings

logger.remove()
logger.add(
    lambda msg: print(msg, end="", flush=True),
    level=settings.log_level,
    colorize=True,
    format="<green>{time:HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan> | {message}",
)

class StepEventBus:
    """每个问答请求一个实例；Plugin emit，编排层 drain 后通过 SSE 推送。"""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    async def emit(self, step: str, message: str, data: dict[str, Any] | None = None) -> None:
        event = {
            "step": step,
            "message": message,
            "data": data or {},
            "ts": time.time(),
        }
        logger.info(f"[{step}] {message}")
        if data:
            logger.debug(f"[{step}] data={json.dumps(data, ensure_ascii=False)[:300]}")
        await self._queue.put(event)

    def drain_ready(self) -> list[dict[str, Any]]:
        """非阻塞排空当前已入队的全部事件（在每个步骤边界调用）。"""
        events: list[dict[str, Any]] = []
        while True:
            try:
                events.append(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        return events
