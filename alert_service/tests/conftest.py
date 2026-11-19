import os
import sys
from pathlib import Path

os.environ["TICKER_ALERT_SKIP_DB"] = "1"
os.environ["TICKER_ALERT_SKIP_LAKE_AUTO"] = "1"

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
