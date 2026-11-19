"""Publish bar payloads to Kafka, or print them in dry-run mode."""

from __future__ import annotations

import json
import logging
from typing import Any, Protocol

from aiokafka import AIOKafkaProducer

log = logging.getLogger(__name__)


class BarPublisher(Protocol):
    async def start(self) -> None: ...

    async def stop(self) -> None: ...

    async def publish(self, bar: dict[str, Any]) -> None: ...


class StdoutPublisher:
    """Print one JSON line per bar. Used when Kafka is not running yet."""

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def publish(self, bar: dict[str, Any]) -> None:
        print(json.dumps(bar, separators=(",", ":")), flush=True)


class KafkaBarPublisher:
    def __init__(self, *, bootstrap: str, topic: str):
        self.bootstrap = bootstrap
        self.topic = topic
        self._producer: AIOKafkaProducer | None = None

    async def start(self) -> None:
        producer = AIOKafkaProducer(
            bootstrap_servers=self.bootstrap,
            value_serializer=lambda value: json.dumps(value).encode("utf-8"),
            key_serializer=lambda value: value.encode("utf-8") if value else None,
            acks="all",
        )
        await producer.start()
        self._producer = producer
        log.info("Kafka producer connected to %s topic=%s", self.bootstrap, self.topic)

    async def stop(self) -> None:
        if self._producer is None:
            return
        await self._producer.stop()
        self._producer = None

    async def publish(self, bar: dict[str, Any]) -> None:
        if self._producer is None:
            raise RuntimeError("Kafka producer is not started.")
        await self._producer.send_and_wait(self.topic, bar, key=str(bar.get("symbol") or ""))
