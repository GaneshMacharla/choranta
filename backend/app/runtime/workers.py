"""
Dedicated thread pools for blocking work during live calls.

Python's default executor (used by asyncio.to_thread) is small (CPU count + 4) and shared with database writes,
recordings and background jobs, so a few slow tools could leave replies waiting for a thread mid-call. LLM
streams and tool calls each get their own pool here; threads only block on network I/O, so they are cheap.
"""
import asyncio
import functools
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from app.core.config import settings

LLM_POOL = ThreadPoolExecutor(max_workers=max(1, settings.VOICE_LLM_THREADS), thread_name_prefix="voice-llm")
TOOL_POOL = ThreadPoolExecutor(max_workers=max(1, settings.VOICE_TOOL_THREADS), thread_name_prefix="voice-tool")


async def run_tool(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Runs a blocking tool call on the tool pool."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(TOOL_POOL, functools.partial(fn, *args, **kwargs))
