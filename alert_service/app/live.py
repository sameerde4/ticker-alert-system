"""Entry point: python -m app.live

Consumes Kafka minute bars and writes open→last price alerts for the watchlist.
Run check still handles news. Leave this process running beside the API during RTH.
"""

from __future__ import annotations

import asyncio
import logging
import signal

from .db import db
from .live_consumer import LiveBarConsumer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("live")


async def _run() -> None:
    await db.connect()
    assert db.pool is not None
    consumer = LiveBarConsumer(db.pool)
    loop = asyncio.get_running_loop()

    def _stop() -> None:
        log.info("Stop requested")
        consumer.request_stop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _stop)
        except NotImplementedError:
            pass
    try:
        await consumer.run()
    finally:
        await db.disconnect()


def main() -> None:
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
