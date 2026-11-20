#!/usr/bin/env bash
# On the EC2 host: pull Alpaca credentials from Secrets Manager into alpaca.env
set -euo pipefail
REGION="${AWS_REGION:-us-east-1}"
SECRET_ID="${ALPACA_SECRET_ID:-market-radar/alpaca}"
OUT="${1:-/opt/market-radar/deploy/alpaca.env}"

json="$(aws secretsmanager get-secret-value --region "$REGION" --secret-id "$SECRET_ID" --query SecretString --output text)"
python3 - "$json" "$OUT" <<'PY'
import json, sys
raw, out = sys.argv[1], sys.argv[2]
data = json.loads(raw)

key = (
    data.get("ALPACA_API_KEY")
    or data.get("ALPACA_API_KEY_ID")
    or data.get("alpaca_api_key_id")
    or data.get("api_key")
    or data.get("key")
    or ""
)
secret = (
    data.get("ALPACA_API_SECRET")
    or data.get("ALPACA_API_SECRET_KEY")
    or data.get("alpaca_api_secret_key")
    or data.get("api_secret")
    or data.get("secret")
    or data.get("password")
    or ""
)

# Console "key/value" form often stores { "<api_key_id>": "<api_secret>" }.
if (not key or not secret) and len(data) == 1:
    only_key, only_val = next(iter(data.items()))
    key, secret = str(only_key), str(only_val)

if not key or not secret:
    raise SystemExit(f"Secret missing key/secret fields; have keys={sorted(data)}")

with open(out, "w", encoding="utf-8") as fh:
    fh.write(f"ALPACA_API_KEY_ID={key}\n")
    fh.write(f"ALPACA_API_SECRET_KEY={secret}\n")
print(f"Wrote {out}")
PY
chmod 600 "$OUT"
