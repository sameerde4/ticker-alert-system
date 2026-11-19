import json

import pytest

from app.publisher import StdoutPublisher


@pytest.mark.asyncio
async def test_stdout_publisher_prints_one_json_line(capsys):
    publisher = StdoutPublisher()
    await publisher.start()
    await publisher.publish(
        {
            "schema": "prices.raw.bars.v1",
            "symbol": "AAPL",
            "ts": "2026-11-18T15:00:00Z",
            "close": 100.0,
        }
    )
    await publisher.stop()
    out = capsys.readouterr().out.strip()
    payload = json.loads(out)
    assert payload["symbol"] == "AAPL"
    assert payload["schema"] == "prices.raw.bars.v1"
