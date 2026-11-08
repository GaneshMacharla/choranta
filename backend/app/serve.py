"""
Production entry point: `python -m app.serve` (HOST / PORT from the environment, default 0.0.0.0:8000).

Plain uvicorn closes every WebSocket the moment it is told to stop, which hangs up all live calls on each
deploy. This server drains first: on the first SIGTERM / Ctrl+C it stops placing new outbound calls, reports
503 on /health, and waits for live calls to end (at most SHUTDOWN_DRAIN_S) before shutting down. A second
signal stops it at once.
"""
import asyncio
import logging
import os
import time
from types import FrameType
from typing import Optional

import uvicorn

from app.core.config import settings
from app.runtime import draining

logger = logging.getLogger("choranta.serve")

DRAIN_POLL_S = 1.0


class DrainingServer(uvicorn.Server):
    _loop: Optional[asyncio.AbstractEventLoop] = None

    async def serve(self, sockets=None) -> None:
        self._loop = asyncio.get_running_loop()
        await super().serve(sockets)

    def handle_exit(self, sig: int, frame: Optional[FrameType]) -> None:
        if draining.is_draining() or self._loop is None or draining.live_calls() == 0:
            super().handle_exit(sig, frame)
            return
        draining.start()
        logger.warning(f"Shutdown requested: draining {draining.live_calls()} live call(s) "
                       f"(up to {settings.SHUTDOWN_DRAIN_S}s); send the signal again to stop now.")
        self._loop.call_soon_threadsafe(lambda: self._loop.create_task(self._drain(sig)))

    async def _drain(self, sig: int) -> None:
        deadline = time.monotonic() + max(0, settings.SHUTDOWN_DRAIN_S)
        while draining.live_calls() > 0 and time.monotonic() < deadline and not self.should_exit:
            await asyncio.sleep(DRAIN_POLL_S)
        remaining = draining.live_calls()
        if remaining:
            logger.warning(f"Drain time is up; shutting down with {remaining} call(s) still live.")
        else:
            logger.info("All calls finished; shutting down.")
        uvicorn.Server.handle_exit(self, sig, None)


def main() -> None:
    config = uvicorn.Config(
        "app.main:app",
        host=os.environ.get("HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", "8000")),
    )
    DrainingServer(config).run()


if __name__ == "__main__":
    main()
