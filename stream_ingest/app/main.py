"""Run the Alpaca delayed-SIP minute-bar producer into Kafka."""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal

from .alpaca_rest import AlpacaRestBarPoller, probe_latest_bars
from .alpaca_ws import AlpacaBarStream
from .config import settings
from .publisher import KafkaBarPublisher, StdoutPublisher
from .symbols import load_symbols, shard_symbols

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("stream_ingest")


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


async def _live_is_armed() -> bool:
    """True when Live alerts are armed (or control URL is unset)."""
    url = (settings.live_control_url or "").strip()
    if not url:
        return True
    import httpx

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            payload = response.json()
        if "armed" in payload:
            return bool(payload["armed"])
        return bool(payload.get("enabled"))
    except Exception as exc:
        log.warning("Live control poll failed (%s); treating as armed.", exc)
        return True


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

    control = (settings.live_control_url or "").strip()
    if control:
        log.info("Producer follows Live arm switch at %s", control)

    while not stop.is_set():
        if control and not await _live_is_armed():
            log.info("Live alerts disarmed — producer idle.")
            try:
                await asyncio.wait_for(stop.wait(), timeout=max(1.0, settings.live_control_poll_seconds))
            except asyncio.TimeoutError:
                continue
            break
        await _run_publish_session(args, symbols, stop=stop)
        if stop.is_set():
            break
        if not control:
            break


async def _run_publish_session(
    args: argparse.Namespace, symbols: list[str], *, stop: asyncio.Event
) -> None:
    # 0 = REST-only (useful when another app already holds the WebSocket slot).
    limit = max(0, settings.alpaca_ws_symbol_limit)
    ws_symbols = symbols[:limit]
    rest_symbols = symbols[limit:] if settings.rest_poll_enabled and not args.ws_only else []
    if args.rest_only:
        ws_symbols = []
        rest_symbols = symbols if settings.rest_poll_enabled else []

    dry_run = args.dry_run or settings.dry_run
    publisher = StdoutPublisher() if dry_run else KafkaBarPublisher(
        bootstrap=settings.kafka_bootstrap_servers,
        topic=settings.kafka_topic_bars,
    )

    log.info(
        "Universe=%s feed=%s websocket=%s rest=%s dry_run=%s topic=%s",
        len(symbols),
        settings.alpaca_feed,
        len(ws_symbols),
        len(rest_symbols),
        dry_run,
        settings.kafka_topic_bars,
    )
    if len(symbols) > limit and not rest_symbols and not args.rest_only:
        log.warning(
            "Alpaca Basic WebSocket cap is %s symbols. Only the first %s will stream. "
            "Enable REST_POLL_ENABLED=1 to cover the rest of the S&P 500 on free.",
            limit,
            limit,
        )

    await publisher.start()
    tasks: list[asyncio.Task] = []
    streams: list[AlpacaBarStream] = []
    poller: AlpacaRestBarPoller | None = None
    control = (settings.live_control_url or "").strip()

    try:
        if ws_symbols and not args.rest_only:
            # One shard only on free Basic. Extra shards are usually rejected.
            for shard in shard_symbols(ws_symbols, limit=limit)[:1]:
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

        async def _watch_disarm() -> None:
            if not control:
                await stop.wait()
                return
            while not stop.is_set():
                if not await _live_is_armed():
                    log.info("Live alerts disarmed — stopping producer session.")
                    return
                try:
                    await asyncio.wait_for(
                        stop.wait(), timeout=max(1.0, settings.live_control_poll_seconds)
                    )
                except asyncio.TimeoutError:
                    continue

        watcher = asyncio.create_task(_watch_disarm(), name="live-arm-watch")
        done, pending = await asyncio.wait(
            [*tasks, watcher],
            return_when=asyncio.FIRST_COMPLETED,
        )
        if watcher in done and stop.is_set():
            log.info("Shutdown requested.")
        for task in tasks:
            task.cancel()
        for stream in streams:
            stream.request_stop()
        if poller is not None:
            poller.request_stop()
        watcher.cancel()
        await asyncio.gather(*tasks, watcher, return_exceptions=True)
        for task in pending:
            task.cancel()
    finally:
        await publisher.stop()


async def run_probe(symbols: list[str], *, dry_run: bool) -> None:
    """One-shot REST check so a closed market does not look like a broken stream."""
    if not dry_run:
        log.info("Probe prints to stdout. Use a normal run (no --probe) once Kafka is up.")
    publisher = StdoutPublisher()
    await publisher.start()
    try:
        bars = await probe_latest_bars(
            data_url=settings.alpaca_data_url,
            key_id=settings.alpaca_api_key_id,
            secret_key=settings.alpaca_api_secret_key,
            feed=settings.alpaca_feed,
            symbols=symbols,
        )
        if not bars:
            log.warning("No delayed bars in the lookback window. Check symbols and Alpaca keys.")
        for bar in bars:
            await publisher.publish(bar)
        log.info("Probe published %s bar(s).", len(bars))
    finally:
        await publisher.stop()


def main() -> None:
    args = parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
