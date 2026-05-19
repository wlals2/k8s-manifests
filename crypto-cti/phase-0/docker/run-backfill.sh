#!/usr/bin/env bash
# crypto-cti BTC indexer (backfill mode) — 일회성 docker run
#
# Usage:
#   ./run-backfill.sh <START> <END>
#
# 예: ./run-backfill.sh 946945 947939
#
# 사전 조건:
#   - bitcoind pruneheight ≤ START 여야 함 (그렇지 않으면 RPC 실패)
#   - 동일 height 범위가 watch와 겹치지 않게 운영자가 보장
set -euo pipefail

START="${1:?Usage: $0 <START> <END>}"
END="${2:?Usage: $0 <START> <END>}"

IMAGE="192.168.1.187:5000/crypto-cti-api:indexer"
NAME="crypto-cti-backfill-${START}-${END}"
ENV_FILE="/home/jimin/crypto-cti/crypto-python-cde/.env"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "ERROR: env file not found: $ENV_FILE" >&2
  exit 1
fi

docker run --rm \
  --name "$NAME" \
  --network host \
  --env-file "$ENV_FILE" \
  -e WATCHLIST_WEBHOOK_URL= \
  "$IMAGE" \
  python main.py btc backfill --start "$START" --end "$END"
