"""Run the Alpaca delayed-SIP minute-bar producer into Kafka."""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
from typing import Any

from .alpaca_rest import AlpacaRestBarPoller, probe_latest_bars
from .alpaca_ws import AlpacaBarStream
from .config import settings
from .publisher import KafkaBarPublisher, StdoutPublisher
from .symbols import load_symbols, prioritize_symbols, shard_symbols, split_ws_rest

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("stream_ingest")

# Soft cap aligned with Alpaca Basic; API also enforces this.
_WS_HARD_CAP = 30


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Alpaca delayed SIP → Kafka minute bars")
    parser.add_argument("--dry-run", action="store_true", help="Print bars to stdout instead of Kafka")
    parser.add_argument("--symbols", default="", help="Comma-separated symbols (overrides file when set)")
    parser.add_argument("--ws-only", action="store_true", help="Do not start the REST poller")
    parser.add_argument("--rest-only", action="store_true", help="Do not open the WebSocket")
    parser.add_argument(
        "--probe",
        action="store_true",
        help="Fetch the latest delayed bar for each symbol once, then exit (works after hours)",
    )
    return parser.parse_args()


async def _fetch_live_control() -> dict[str, Any]:
    """Poll Live status (armed + optional ws_symbols from Settings)."""
    url = (settings.live_control_url or "").strip()
    if not url:
        return {"armed": True, "ws_symbols": None, "ws_limit": None}
    import httpx

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, dict):
            return {"armed": True, "ws_symbols": None, "ws_limit": None}
        armed = bool(payload["armed"]) if "armed" in payload else bool(payload.get("enabled"))
        ws_raw = payload.get("ws_symbols")
        ws_symbols = (
            [str(item).strip().upper() for item in ws_raw if str(item).strip()]
            if isinstance(ws_raw, list)
            else None
        )
        limit_raw = payload.get("ws_limit")
        try:
            ws_limit = int(limit_raw) if limit_raw is not None else None
        except (TypeError, ValueError):
            ws_limit = None
        return {"armed": armed, "ws_symbols": ws_symbols, "ws_limit": ws_limit}
    except Exception as exc:
        log.warning("Live control poll failed (%s); treating as armed with env defaults.", exc)
        return {"armed": True, "ws_symbols": None, "ws_limit": None}


async def _live_is_armed() -> bool:
    """True when Live alerts are armed (or control URL is unset)."""
    payload = await _fetch_live_control()
    return bool(payload.get("armed"))


def _env_ws_priority() -> list[str]:
    return load_symbols(symbols_csv=settings.alpaca_ws_priority_symbols, symbols_file="")


def _resolve_feed(
    universe: list[str],
    control: dict[str, Any],
    *,
    rest_only: bool,
    ws_only: bool,
) -> tuple[list[str], list[str], int, str]:
    """Return (ws_symbols, rest_symbols, limit, fingerprint)."""
    limit = control.get("ws_limit")
    if limit is None:
        limit = settings.alpaca_ws_symbol_limit
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = settings.alpaca_ws_symbol_limit
    limit = max(0, min(_WS_HARD_CAP, limit))

    api_ws = control.get("ws_symbols")
    if isinstance(api_ws, list) and api_ws:
        priority = [str(item).strip().upper() for item in api_ws if str(item).strip()]
    else:
        priority = _env_ws_priority()
        if not priority:
            # Legacy: first N of the universe when no Settings list / env priority.
            priority = list(universe)

    if rest_only or limit == 0:
        ws_symbols: list[str] = []
        rest_symbols = list(universe) if settings.rest_poll_enabled and not ws_only else []
    else:
        ws_symbols, rest_symbols = split_ws_rest(
            universe,
            ws_priority=priority,
            limit=limit,
            rest_enabled=settings.rest_poll_enabled and not ws_only,
        )

    fingerprint = f"{limit}|{','.join(ws_symbols)}"
    return ws_symbols, rest_symbols, limit, fingerprint


async def run(args: argparse.Namespace) -> None:
    if not settings.alpaca_api_key_id.strip() or not settings.alpaca_api_secret_key.strip():
        raise SystemExit(
            "Set ALPACA_API_KEY_ID and ALPACA_API_SECRET_KEY in stream_ingest/.env "
            "(Paper keys from https://app.alpaca.markets/ are fine)."
        )

    symbols = load_symbols(
        symbols_csv=args.symbols or settings.symbols,
        symbols_file="" if (args.symbols or settings.symbols) else settings.symbols_file,
    )
    env_priority = _env_ws_priority()
    if env_priority and not (args.symbols or settings.symbols):
        symbols = prioritize_symbols(env_priority, symbols)
    if not symbols:
        raise SystemExit("No symbols loaded. Check SYMBOLS, SYMBOLS_FILE, or data/sp500_symbols.txt.")

    if args.probe:
        await run_probe(symbols, dry_run=args.dry_run or settings.dry_run)
        return

    stop = asyncio.Event()

    def _stop(*_args: object) -> None:
        stop.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _stop)
        except NotImplementedError:
            pass

    control_url = (settings.live_control_url or "").strip()
    if control_url:
        log.info("Producer follows Live arm switch + WebSocket list at %s", control_url)

    while not stop.is_set():
        control = await _fetch_live_control()
        if control_url and not control.get("armed"):
            log.info("Live alerts disarmed — producer idle.")
            try:
                await asyncio.wait_for(stop.wait(), timeout=max(1.0, settings.live_control_poll_seconds))
            except asyncio.TimeoutError:
                continue
            continue

        ws_symbols, rest_symbols, _limit, fingerprint = _resolve_feed(
            symbols,
            control,
            rest_only=args.rest_only,
            ws_only=args.ws_only,
        )
        await _run_publish_session(
            args,
            universe=symbols,
            ws_symbols=ws_symbols,
            rest_symbols=rest_symbols,
            fingerprint=fingerprint,
            stop=stop,
        )
        if stop.is_set():
            break
        if not control_url:
            break


async def _run_publish_session(
    args: argparse.Namespace,
    *,
    universe: list[str],
    ws_symbols: list[str],
    rest_symbols: list[str],
    fingerprint: str,
    stop: asyncio.Event,
) -> None:
    dry_run = args.dry_run or settings.dry_run
    publisher = StdoutPublisher() if dry_run else KafkaBarPublisher(
        bootstrap=settings.kafka_bootstrap_servers,
        topic=settings.kafka_topic_bars,
    )

    log.info(
        "Universe=%s feed=%s websocket=%s rest=%s dry_run=%s topic=%s",
        len(universe),
        settings.alpaca_feed,
        len(ws_symbols),
        len(rest_symbols),
        dry_run,
        settings.kafka_topic_bars,
    )
    if ws_symbols:
        log.info("WebSocket symbols: %s", ",".join(ws_symbols))

    await publisher.start()
    tasks: list[asyncio.Task] = []
    streams: list[AlpacaBarStream] = []
    poller: AlpacaRestBarPoller | None = None
    control_url = (settings.live_control_url or "").strip()

    try:
        if ws_symbols and not args.rest_only:
            # One shard only on free Basic. Extra shards are usually rejected.
            shard_limit = max(1, len(ws_symbols))
            for shard in shard_symbols(ws_symbols, limit=shard_limit)[:1]:
                stream = AlpacaBarStream(
                    url=settings.ws_url,
                    key_id=settings.alpaca_api_key_id,
                    secret_key=settings.alpaca_api_secret_key,
                    feed=settings.alpaca_feed,
                    symbols=shard,
                    publisher=publisher,
                )
                streams.append(stream)
                tasks.append(asyncio.create_task(stream.run(), name="alpaca-ws"))

        if rest_symbols and not args.ws_only:
            poller = AlpacaRestBarPoller(
                data_url=settings.alpaca_data_url,
                key_id=settings.alpaca_api_key_id,
                secret_key=settings.alpaca_api_secret_key,
                feed=settings.alpaca_feed,
                symbols=rest_symbols,
                publisher=publisher,
                poll_seconds=settings.rest_poll_seconds,
                symbols_per_request=settings.rest_symbols_per_request,
            )
            tasks.append(asyncio.create_task(poller.run(), name="alpaca-rest"))

        if not tasks:
            raise SystemExit("Nothing to run. Check --ws-only / --rest-only and symbol lists.")

        async def _watch_control() -> None:
            if not control_url:
                await stop.wait()
                return
            while not stop.is_set():
                control = await _fetch_live_control()
                if not control.get("armed"):
                    log.info("Live alerts disarmed — stopping producer session.")
                    return
                _, _, _, next_fp = _resolve_feed(
                    universe,
                    control,
                    rest_only=args.rest_only,
                    ws_only=args.ws_only,
                )
                if next_fp != fingerprint:
                    log.info("WebSocket symbol list changed — restarting producer session.")
                    return
                try:
                    await asyncio.wait_for(
                        stop.wait(), timeout=max(1.0, settings.live_control_poll_seconds)
                    )
                except asyncio.TimeoutError:
                    continue

        watcher = asyncio.create_task(_watch_control(), name="live-control-watch")
        done, pending = await asyncio.wait(
            [*tasks, watcher],
            return_when=asyncio.FIRST_COMPLETED,
        )
        if watcher in done and stop.is_set():
            log.info("Shutdown requested.")
        for task in tasks:
            task.cancel()
        for stream in streams:
            stream.stop()
        if poller is not None:
            poller.stop()
        watcher.cancel()
        await asyncio.gather(*tasks, watcher, return_exceptions=True)
    finally:
        await publisher.stop()


async def run_probe(symbols: list[str], *, dry_run: bool) -> None:
    """One-shot REST check so a closed market does not look like a broken stream."""
    rows = await probe_latest_bars(
        data_url=settings.alpaca_data_url,
        key_id=settings.alpaca_api_key_id,
        secret_key=settings.alpaca_api_secret_key,
        feed=settings.alpaca_feed,
        symbols=symbols,
    )
    publisher = StdoutPublisher() if dry_run else KafkaBarPublisher(
        bootstrap=settings.kafka_bootstrap_servers,
        topic=settings.kafka_topic_bars,
    )
    await publisher.start()
    try:
        for bar in rows:
            await publisher.publish(bar)
        log.info("Probe published %s bar(s).", len(rows))
    finally:
        await publisher.stop()


def main() -> None:
    asyncio.run(run(parse_args()))


if __name__ == "__main__":
    main()
