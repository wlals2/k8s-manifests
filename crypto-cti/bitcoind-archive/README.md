# bitcoind-archive — Full Archive Bitcoin Node (ADR-0012 Option B)

운영 pruned bitcoind와 **공존**하는 archive 노드. txindex=1, prune=0, 700Gi local-path.

## 위치 결정 이유

- SoT는 `/home/jimin/k8s-manifests/` (인프라 매니페스트 레포)
- 기존 운영 bitcoind 매니페스트가 `crypto-cti/phase-0/20-bitcoind.yaml`
- archive는 phase-0와 동급의 별도 컴포넌트 → `crypto-cti/bitcoind-archive/` 형제 디렉터리
- crypto-cti-ofac/k8s/는 OFAC 앱 코드 레포라 인프라와 분리

## 파일

| 파일 | 역할 |
|------|------|
| `00-pvc.yaml` | `data-bitcoind-archive-0` PVC 700Gi local-path (worker2 귀속) |
| `10-statefulset.yaml` | bitcoind-archive STS + ConfigMap (txindex=1, prune=0, dbcache=4096) |
| `20-service.yaml` | ClusterIP rpc:8332 / zmq:28332,28333 |

## 기존 인프라 재사용

| 항목 | 값 | 근거 |
|------|-----|------|
| 이미지 | `lncm/bitcoind:v27.1` | `phase-0/20-bitcoind.yaml:132` |
| Secret | `bitcoind-rpc-secret` (운영과 공유) | `kubectl get secret bitcoind-rpc-secret -n crypto-cti` 존재 |
| ZMQ 토픽 | `zmqpubhashblock`, `zmqpubrawtx` | `phase-0/20-bitcoind.yaml:51-53` — 인덱서 코드(btc/rpc.py:133) 변경 없이 RPC URL 전환만으로 호환 |
| 포트 | 8332/8333/28332/28333 | 운영과 동일 |
| StorageClass | `local-path` | core.md:100 default SC |

## 적용 순서

```bash
# 0. 사전 점검 — worker2 /mnt/data 700GB+ 여유 확인 (사용자 SSH)
ssh jimin@192.168.1.62 'df -h /mnt/data'
# Avail >= 700G 확인

# 1. PVC 먼저 (WaitForFirstConsumer라 PV는 Pod 스케줄 시점에 생성됨)
kubectl apply -f /home/jimin/k8s-manifests/crypto-cti/bitcoind-archive/00-pvc.yaml

# 2. STS + ConfigMap + Service
kubectl apply -f /home/jimin/k8s-manifests/crypto-cti/bitcoind-archive/10-statefulset.yaml
kubectl apply -f /home/jimin/k8s-manifests/crypto-cti/bitcoind-archive/20-service.yaml

# 3. 기동 확인
kubectl get pod -n crypto-cti -l app=bitcoind-archive -w
kubectl get pvc data-bitcoind-archive-0 -n crypto-cti
# → STATUS Bound, 노드 = k8s-worker2 확인
```

## IBD 모니터링 (1~2주 소요)

```bash
# RPC로 진행률 확인 — 매일 한 번 권장
kubectl exec -n crypto-cti bitcoind-archive-0 -- \
  bitcoin-cli -rpcuser=$RPC_USER -rpcpassword=$RPC_PASSWORD getblockchaininfo \
  | jq '{blocks, headers, verificationprogress, size_on_disk}'

# verificationprogress: 0.0 → 1.0 (1.0이면 IBD 완료)
# size_on_disk: 디스크 점유량 — 600GB 근처 도달 후 인덱서 전환 가능

# 디스크 사용량 추이
ssh jimin@192.168.1.62 'df -h /mnt/data && du -sh /opt/local-path-provisioner/* 2>/dev/null | grep archive'
```

## 인덱서 전환 가이드 (IBD 완료 후)

```bash
# 인덱서 Deployment(또는 Pod) 환경변수 업데이트
# 운영 → archive 전환
kubectl set env -n crypto-cti deploy/crypto-cti-api \
  BTC_RPC_URL=http://bitcoind-archive.crypto-cti.svc.cluster.local:8332 \
  BTC_ZMQ_URL=tcp://bitcoind-archive.crypto-cti.svc.cluster.local:28332

# crypto-cti-watch는 k8s-cp 호스트 docker (core.md:80) — 별도 컨테이너 env 재시작
# (실제 docker-compose 또는 systemd unit 파일 위치는 운영 SoT 따라)

# 롤백 시 (archive 문제 발생):
kubectl set env -n crypto-cti deploy/crypto-cti-api \
  BTC_RPC_URL=http://bitcoind.crypto-cti.svc.cluster.local:8332 \
  BTC_ZMQ_URL=tcp://bitcoind.crypto-cti.svc.cluster.local:28332
```

## 운영 영향 분석

- **IBD 기간 (1~2주)**: archive RPC 응답 매우 느림 (`getblockchaininfo`는 응답하지만 `getrawtransaction`/`gettxout`은 IBD 중 거절). 인덱서는 IBD 완료 전까지 절대 archive로 가리키지 않음 — 운영 pruned bitcoind 그대로 사용.
- **공존 비용**: worker2 RAM 추가 2~6Gi 점유, CPU 1~2 core. ES-poc/kibana-poc/mvp와 공존 확인됨 (capacity-advisor: 여유 10.7Gi).
- **디스크 증가**: 600GB 시작 → 1년 후 ~1.2TB (월 ~50GB). 700Gi PVC는 1년차 후 확장 필요. local-path는 `allowVolumeExpansion: false` (core.md:100) → 후속 ADR로 확장 전략 (수동 PV 재생성 vs Longhorn 재도입) 결정 필요.
- **P2P 인바운드**: archive는 NodePort 미설정 — outbound로만 동기화. 운영 bitcoind-p2p NodePort 30833 유지.

## 운영 위험

| 위험 | 영향 | 완화 |
|------|------|------|
| worker2 /mnt/data 700GB 부족 | PV 바인딩 실패 | 사전 `df -h` 확인 (필수 게이트) |
| IBD 중 worker2 재기동 | 디스크 손상 시 IBD 처음부터 | StatefulSet 자동 재기동, chainstate corruption 시 `-reindex-chainstate` |
| dbcache 4096이 부족해 IBD 느림 | IBD 1주 → 2~3주 | limits 8Gi로 상향 + dbcache=6144 (worker2 여유 모니터링 후) |
| 운영 pruned bitcoind와 RPC user/pass 공유 | 한쪽 침해 시 양쪽 영향 | 후속 ADR로 archive 전용 Secret 분리 |
| 인덱서 archive 전환 후 호환성 오류 | 인덱싱 중단 | env 즉시 롤백 (위 `kubectl set env`) |

## 롤백 절차

```bash
# 1. 인덱서를 pruned로 되돌림 (전환했다면)
kubectl set env -n crypto-cti deploy/crypto-cti-api \
  BTC_RPC_URL=http://bitcoind.crypto-cti.svc.cluster.local:8332

# 2. archive STS 중지 (PVC는 retain — IBD 진행분 보존)
kubectl delete sts bitcoind-archive -n crypto-cti
kubectl delete svc bitcoind-archive -n crypto-cti
kubectl delete cm bitcoind-archive-config -n crypto-cti

# 3. 완전 폐기 시 (700GB 회수)
kubectl delete pvc data-bitcoind-archive-0 -n crypto-cti
# → local-path provisioner가 worker2의 디렉터리 자동 삭제

# 4. Git revert
git -C /home/jimin/k8s-manifests revert <commit>
```

## 알려진 한계 / 후속 ADR

1. **디스크 확장 전략 미정** — local-path `allowVolumeExpansion: false`. 1년 후 1.2TB 도달 시 PVC 확장 불가 → 후속 ADR (수동 PV 마이그레이션 vs Longhorn 재도입) 필요.
2. **Secret 공유** — 운영/archive가 `bitcoind-rpc-secret` 공유. 보안 분리가 필요해지면 후속 ADR로 archive 전용 Secret + 인덱서 envFrom 분기.
3. **IBD 가속 옵션 미적용** — `assumevalid` / `prune=0 + reindex`로 가속 가능하지만 첫 시도는 기본 설정으로 진행. IBD 1주 초과 시 후속 ADR로 튜닝.
4. **NetworkPolicy 미적용** — crypto-cti namespace 전반에 NetworkPolicy 없음. archive RPC도 동일 — 후속 ADR로 namespace 전체 정책 도입 시 동시 적용.
5. **모니터링 미연동** — Prometheus가 아직 미설치 (core.md:120). IBD 진행률을 자동 알림하려면 후속에 bitcoin_exporter + Prometheus 필요.

## 검증 명령

```bash
# STS 롤아웃
kubectl rollout status sts/bitcoind-archive -n crypto-cti --timeout=10m

# Pod 로그 (IBD 시작 확인 — "UpdateTip" 메시지가 흘러야 함)
kubectl logs -n crypto-cti bitcoind-archive-0 -f | grep -E "UpdateTip|progress"

# RPC ping (Secret 환경변수 사용)
kubectl exec -n crypto-cti bitcoind-archive-0 -- \
  sh -c 'bitcoin-cli -rpcuser=$RPC_USER -rpcpassword=$RPC_PASSWORD getblockcount'

# Service DNS 도달성 (다른 Pod에서)
kubectl run -n crypto-cti curltest --image=curlimages/curl --rm -it --restart=Never -- \
  curl -sv bitcoind-archive.crypto-cti.svc.cluster.local:8332
# → 401 Unauthorized 응답이면 RPC LISTEN 정상 (auth 없이 호출했으므로 401이 맞음)
```
