# crypto-cti BTC indexer — docker 운영

호스트 venv `python main.py btc {watch,backfill}`을 docker 컨테이너로 옮긴 운영 스크립트.
K8s 마이그레이션은 의도적으로 보류 (단일 호스트 + 단일 컨테이너로 충분).

런타임: docker.io 28.2.2 (2026-05-05 `apt install docker.io`로 설치, systemd enable)

## 전제

- bitcoind / postgres 는 K8s namespace `crypto-cti`에서 ClusterIP로 운영 중
- 호스트는 K8s control plane(`k8s-cp`, 192.168.1.187)이라 kube-proxy iptables를 통해
  ClusterIP에 접근 가능 → docker `--network host`로 그대로 사용
- 이미지: `192.168.1.187:5000/crypto-cti-api:indexer`
  (API용 `phase-0` 태그와 분리. API Pod의 ImagePullPolicy=IfNotPresent라
  같은 태그로 덮어쓰면 인식 차이가 생기므로 indexer 전용 태그를 사용)
- insecure registry `192.168.1.187:5000`은 `/etc/docker/daemon.json`에 등록됨

## 빌드

이미지는 OCI 표준이라 podman build로 빌드한 이미지도 docker에서 그대로 동작.
신규 빌드는 docker 사용 권장:

```bash
cd /home/jimin/crypto-cti/crypto-python-cde
docker build -t 192.168.1.187:5000/crypto-cti-api:indexer .
docker push 192.168.1.187:5000/crypto-cti-api:indexer
```

## watch (상시 실행)

```bash
./run-watch.sh
docker logs -f crypto-cti-watch
```

검증:
- `Starting real-time block watch via ZMQ`
- `ZMQ connected to tcp://10.96.50.20:28332`
- 평균 10분 내 새 블록 수신 로그

## backfill (일회성)

```bash
# 예: 946,945 ~ 947,939 범위
./run-backfill.sh 946945 947939
```

⚠️ 동일 범위가 watch와 겹치면 PK 충돌. 단발 실행 후 자연 종료(`--rm`).

## 자동 재시작

`--restart=always` 정책으로 컨테이너 종료 시 docker가 재시작.
docker.service가 systemd enable 상태라 호스트 재부팅 시 dockerd 자동 기동 →
`--restart=always` 컨테이너도 자동 기동 충족 (별도 systemd unit 불필요).

## 정리

```bash
docker stop crypto-cti-watch
docker rm crypto-cti-watch
```
