#!/usr/bin/env bash
# crypto-cti BTC indexer (watch mode) — docker 컨테이너 운영
#
# 호스트 venv `python main.py btc watch`를 docker 컨테이너로 옮긴다.
# K8s ClusterIP(postgres/bitcoind) 접근을 위해 --network host 사용
# (kube-proxy iptables가 호스트 네임스페이스에서 ClusterIP 라우팅).
#
# 운영:
#   ./run-watch.sh         # 시작 (기존 컨테이너 있으면 교체)
#   docker logs -f crypto-cti-watch
#   docker stop crypto-cti-watch
set -euo pipefail

IMAGE="192.168.1.187:5000/crypto-cti-api:indexer"
NAME="crypto-cti-watch"
ENV_FILE="/home/jimin/crypto-cti/crypto-python-cde/.env"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "ERROR: env file not found: $ENV_FILE" >&2
  exit 1
fi

docker rm -f "$NAME" >/dev/null 2>&1 || true

docker run -d \
  --name "$NAME" \
  --restart=always \
  --network host \
  --env-file "$ENV_FILE" \
  --log-opt max-size=50m \
  --log-opt max-file=5 \
  "$IMAGE" \
  python main.py btc watch

echo "started: $NAME"
docker ps --filter name="$NAME" --format 'table {{.Names}}\t{{.Status}}\t{{.Image}}'
