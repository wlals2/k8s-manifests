# crypto-cti Phase 0 — APPLY 절차

> BTC-only PoC. local-path-provisioner + Postgres + bitcoind(pruned).
> 기본 실행 모델은 Kubernetes Pod 내부 실행 + Service DNS 사용.
> host 직접 실행은 개발/디버그용 port-forward 경로로만 유지한다.

배치 계획:
- PostgreSQL → **k8s-worker3** (RAM 19Gi, PG 캐시에 유리)
- bitcoind → **k8s-worker1** (`/mnt/data` 200GB LVM, RAM 14Gi)
- local-path-provisioner 데이터 경로 → **/mnt/data/local-path-provisioner** (모든 노드 공통)

---

## 0. 사전 준비 — Longhorn 잔여 데이터 정리

> 이 단계는 worker1·worker3에서 과거 Longhorn을 사용했던 흔적이 남아 있을 때만
> 수행한다. `/mnt/data/replicas`, `/mnt/data/longhorn` 등 잔여 디렉터리가 있으면
> local-path-provisioner가 같은 마운트 포인트를 공유하므로 디스크 용량 회수 +
> 혼동 방지를 위해 미리 삭제한다.

각 대상 노드(k8s-worker1, k8s-worker3)에서 SSH 접속 후 확인 → 삭제:

```bash
# 1) 마운트와 잔여 디렉터리 점검
df -h /mnt/data
ls -la /mnt/data
# 예상되는 잔여물: replicas/, longhorn/, longhorn-disk.cfg, engine-binaries/

# 2) Longhorn 컴포넌트가 K8s에 남아있지 않은지 먼저 확인 (cp 노드에서)
#    있으면 먼저 namespace 삭제 후 노드 정리 진행
kubectl get ns longhorn-system 2>/dev/null && echo "Longhorn 남아있음 — 먼저 helm uninstall"

# 3) 잔여 데이터 삭제 (각 대상 노드에서)
sudo rm -rf /mnt/data/replicas
sudo rm -rf /mnt/data/longhorn
sudo rm -f  /mnt/data/longhorn-disk.cfg
sudo rm -rf /mnt/data/engine-binaries

# 4) local-path 경로 준비 (provisioner가 자동 생성하지만 사전 확인)
ls -la /mnt/data/local-path-provisioner 2>/dev/null || echo "없음 — provisioner setup 스크립트가 자동 생성"
```

> 경로가 없어도 provisioner의 setup 스크립트(`mkdir -m 0777 -p $VOL_DIR`)가
> PVC 생성 시 자동 생성한다. 사전 mkdir 불필요.

---

## 1. Secret 평문 교체

`01-secrets.yaml`의 `CHANGE_ME_*` 값을 강한 패스워드로 교체.
또는 파일 적용 대신 kubectl로 직접 생성:

```bash
kubectl create namespace crypto-cti

PG_PWD=$(openssl rand -base64 24 | tr -d '/+=')
RPC_PWD=$(openssl rand -base64 24 | tr -d '/+=')
API_KEY=$(openssl rand -base64 32 | tr -d '/+=')

kubectl create secret generic postgres-secret -n crypto-cti \
  --from-literal=POSTGRES_USER=crypto \
  --from-literal=POSTGRES_DB=crypto_cti \
  --from-literal=POSTGRES_PASSWORD="$PG_PWD"

kubectl create secret generic bitcoind-rpc-secret -n crypto-cti \
  --from-literal=RPC_USER=cryptocti \
  --from-literal=RPC_PASSWORD="$RPC_PWD"

kubectl create secret generic crypto-cti-env -n crypto-cti \
  --from-literal=DATABASE_URL="postgresql://crypto:${PG_PWD}@postgres.crypto-cti.svc.cluster.local:5432/crypto_cti" \
  --from-literal=BTC_RPC_URL="http://bitcoind.crypto-cti.svc.cluster.local:8332" \
  --from-literal=BTC_RPC_USER=cryptocti \
  --from-literal=BTC_RPC_PASSWORD="$RPC_PWD" \
  --from-literal=BTC_ZMQ_URL="tcp://bitcoind.crypto-cti.svc.cluster.local:28332" \
  --from-literal=API_KEYS="$API_KEY"
```

> `crypto-cti-env`는 Pod 내부 실행 전용이다. host에서 Python을 직접 실행할 때는
> 아래 "host 개발/디버그" 섹션의 `127.0.0.1` port-forward `.env`를 별도로 사용한다.

비-시크릿 튜닝값(BACKFILL_BATCH_SIZE 등)은 별도 ConfigMap으로 분리 관리한다.
Secret과 분리하는 이유: Secret은 RBAC로 강하게 보호되고, ConfigMap은 누구나 읽어도
안전한 평문 값을 담는다. 변경 시 Pod 재시작만 하면 즉시 반영.

```bash
kubectl create configmap crypto-cti-tuning -n crypto-cti \
  --from-literal=BTC_BACKFILL_BATCH_SIZE=20 \
  --from-literal=ETH_BACKFILL_BATCH_SIZE=5 \
  --from-literal=TRON_BACKFILL_BATCH_SIZE=20 \
  --from-literal=ETH_TRACE_ENABLED=false \
  --from-literal=LOG_LEVEL=INFO \
  --dry-run=client -o yaml | kubectl apply -f -
```

> ⚠️ 30-api.yaml의 Deployment가 이 ConfigMap을 envFrom으로 참조한다.
> 누락 시 Pod이 `CreateContainerConfigError`로 시작 실패한다.

---

## 2. local-path-provisioner 설치 (StorageClass 없는 경우만)

데이터 경로: `/mnt/data/local-path-provisioner` (manifest의 ConfigMap에 명시).
모든 노드에서 같은 경로 사용. PVC 생성 시 setup 스크립트가 자동 mkdir.

```bash
kubectl get storageclass
# 비어있으면 진행
kubectl apply -f /home/jimin/k8s-manifests/storage/local-path-provisioner.yaml
kubectl rollout status deployment/local-path-provisioner -n local-path-storage
kubectl get storageclass
# local-path (default) 표시 확인

# 적용된 nodePathMap 확인
kubectl get cm local-path-config -n local-path-storage -o jsonpath='{.data.config\.json}'
# → "/mnt/data/local-path-provisioner" 가 보여야 정상
```

---

## 3. Namespace + Secret

```bash
kubectl apply -f /home/jimin/k8s-manifests/crypto-cti/phase-0/00-namespace.yaml
# Secret은 1번에서 이미 생성했으면 스킵, placeholder로 둘 거면 아래:
# kubectl apply -f /home/jimin/k8s-manifests/crypto-cti/phase-0/01-secrets.yaml
```

---

## 4. PostgreSQL StatefulSet (k8s-worker3 고정)

```bash
kubectl apply -f /home/jimin/k8s-manifests/crypto-cti/phase-0/10-postgres.yaml
kubectl rollout status statefulset/postgres -n crypto-cti --timeout=180s

# 노드 배치 확인 (k8s-worker3에 떠야 정상)
kubectl get pod -n crypto-cti -l app=postgres -o wide

kubectl get pvc -n crypto-cti
kubectl exec -n crypto-cti postgres-0 -- pg_isready -U crypto -d crypto_cti
```

---

## 5. 스키마 적용 (schema.sql)

```bash
# ConfigMap 생성 (또는 갱신)
kubectl create configmap crypto-cti-schema -n crypto-cti \
  --from-file=schema.sql=/home/jimin/crypto-cti/crypto-python-cde/db/schema.sql \
  --dry-run=client -o yaml | kubectl apply -f -

# 기존 Job 제거 후 재실행
kubectl delete job apply-schema -n crypto-cti --ignore-not-found
kubectl apply -f /home/jimin/k8s-manifests/crypto-cti/phase-0/11-postgres-schema-job.yaml

# 결과 확인
kubectl wait --for=condition=complete job/apply-schema -n crypto-cti --timeout=120s
kubectl logs -n crypto-cti job/apply-schema

# 테이블 확인
kubectl exec -n crypto-cti postgres-0 -- psql -U crypto -d crypto_cti -c '\dt'
```

---

## 6. bitcoind 배포 (k8s-worker1 고정)

```bash
kubectl apply -f /home/jimin/k8s-manifests/crypto-cti/phase-0/20-bitcoind.yaml

# 노드 배치 확인 (k8s-worker1에 떠야 정상)
kubectl get pod -n crypto-cti -l app=bitcoind -o wide

kubectl get pod -n crypto-cti -l app=bitcoind -w
# Running 되면 Ctrl+C
```

---

## 7. IBD (Initial Block Download) 모니터링

> ⚠️ 12~48시간 소요. 사용자가 직접 진행 (2분 초과 명령 — 중간 모니터링만).

```bash
# 진행률 (verificationprogress: 0.0 → 1.0)
kubectl exec -n crypto-cti bitcoind-0 -- bitcoin-cli -rpcuser=cryptocti -rpcpassword=$RPC_PWD getblockchaininfo \
  | grep -E 'blocks|headers|verificationprogress|pruned|pruneheight|size_on_disk'

# peer 수
kubectl exec -n crypto-cti bitcoind-0 -- bitcoin-cli -rpcuser=cryptocti -rpcpassword=$RPC_PWD getconnectioncount

# 디스크 사용량 (50Gi PVC 한도)
kubectl exec -n crypto-cti bitcoind-0 -- du -sh /data/.bitcoin

# 로그 (헤더 동기화 → 블록 다운로드 단계 확인)
kubectl logs -n crypto-cti bitcoind-0 --tail=50
```

IBD 완료 기준: `verificationprogress` ≥ 0.9999 AND `blocks` == `headers`

---

## 8. RPC 연결 검증

```bash
# Service DNS 확인 (Pod 안에서는 CoreDNS가 *.svc.cluster.local을 해석)
kubectl run -n crypto-cti --rm -it dnstest --image=busybox:1.36 --restart=Never -- \
  nslookup postgres.crypto-cti.svc.cluster.local

kubectl run -n crypto-cti --rm -it dnstest --image=busybox:1.36 --restart=Never -- \
  nslookup bitcoind.crypto-cti.svc.cluster.local

# 클러스터 내부에서 (debug pod)
kubectl run -n crypto-cti --rm -it curltest --image=curlimages/curl --restart=Never -- \
  curl -s --user cryptocti:$RPC_PWD \
  -H 'content-type: text/plain;' \
  --data-binary '{"jsonrpc":"1.0","id":"x","method":"getblockchaininfo","params":[]}' \
  http://bitcoind.crypto-cti.svc.cluster.local:8332/
```

---

## 9. API 이미지 빌드 + 배포 (권장: Pod 내부 실행)

API를 Kubernetes Pod로 실행해야 Service DNS를 그대로 사용할 수 있다.
이미지는 로컬 레지스트리 `192.168.1.187:5000`에 push한다.

**옵션 A — docker 사용 (권장)**:
```bash
cd /home/jimin/crypto-cti/crypto-python-cde
docker build -t 192.168.1.187:5000/crypto-cti-api:phase-0 .
docker push 192.168.1.187:5000/crypto-cti-api:phase-0
```

**옵션 B — buildah (docker 미설치 또는 cri-o 환경)**:
```bash
cd /home/jimin/crypto-cti/crypto-python-cde
sudo buildah --storage-driver overlay --root /var/lib/containers/storage \
  bud -t localhost/crypto-cti-api:0.1.0 .
sudo buildah --storage-driver overlay --root /var/lib/containers/storage \
  push --tls-verify=false \
  localhost/crypto-cti-api:0.1.0 \
  docker://192.168.1.187:5000/crypto-cti-api:phase-0
```

> registry는 insecure(HTTP). 모든 노드의 cri-o가 192.168.1.187:5000을
> insecure registry로 인식하도록 사전 설정 필요 (이미 hugo-blog가 사용 중이면 OK).

배포:
```bash
kubectl apply -f /home/jimin/k8s-manifests/crypto-cti/phase-0/30-api.yaml
kubectl rollout status deployment/crypto-cti-api -n crypto-cti --timeout=180s
kubectl get pod -n crypto-cti -l app=crypto-cti-api -o wide
```

API health와 DB 연결 확인:

```bash
kubectl run -n crypto-cti --rm -it curlapi --image=curlimages/curl --restart=Never -- \
  curl -s http://crypto-cti-api.crypto-cti.svc.cluster.local:8000/health
```

API key 보호가 켜져 있으므로 일반 API 호출은 `X-API-Key`를 붙인다:

```bash
kubectl run -n crypto-cti --rm -it curlapi --image=curlimages/curl --restart=Never -- \
  curl -s -H "X-API-Key: $API_KEY" \
  http://crypto-cti-api.crypto-cti.svc.cluster.local:8000/api/v1/watchlist
```

---

## 10. Host 개발/디버그 실행 (예외 경로)

bitcoind RPC/ZMQ는 ClusterIP라 host에선 접근 불가. `kubectl port-forward`로 노출:

```bash
# 별도 터미널 3개 (또는 백그라운드)
kubectl port-forward -n crypto-cti svc/postgres 5432:5432 &
kubectl port-forward -n crypto-cti svc/bitcoind 8332:8332 &
kubectl port-forward -n crypto-cti svc/bitcoind 28332:28332 &
```

`/home/jimin/crypto-cti/crypto-python-cde/.env` (port-forward 기준):
```
DATABASE_URL=postgresql://crypto:<PG_PWD>@127.0.0.1:5432/crypto_cti
BTC_RPC_URL=http://127.0.0.1:8332
BTC_RPC_USER=cryptocti
BTC_RPC_PASSWORD=<RPC_PWD>
BTC_ZMQ_URL=tcp://127.0.0.1:28332
LOG_LEVEL=INFO
```

실행:
```bash
cd /home/jimin/crypto-cti/crypto-python-cde
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python main.py btc watch        # ZMQ 기반 실시간 수신
# 또는
python main.py btc backfill --start $(... pruneheight ...) --end tip
```

> pruned 한계: `pruneheight` 이전 블록은 backfill 불가. `getblockchaininfo`의 `pruneheight` 확인.

---

## 10.5 Phase 0.5 — Indexer 컨테이너화 (watch + backfill)

> **현재 운영 방식 (2026-05-05 기준)**
>
> K8s 마이그레이션은 의도적으로 보류했다. 단순함 우선.
> 인덱서는 k8s-cp 호스트 docker(docker.io 28.2.2, systemd enable)로 운영 중이다.
>
> - watch: `phase-0/docker/run-watch.sh` → `crypto-cti-watch` 컨테이너, `--restart=always`
> - backfill: `phase-0/docker/run-backfill.sh <START> <END>` → 일회성 `--rm` 컨테이너
> - 이미지: `192.168.1.187:5000/crypto-cti-api:indexer` (API용 `:phase-0`와 분리)
>
> 아래 K8s 절차에서 참조하는 manifest 두 개는 [`_archive_k8s/`](_archive_k8s/)로
> 이동했다. 추후 K8s 마이그레이션 의도 시 `_archive_k8s/README.md` 절차에 따라
> `phase-0/`로 다시 옮겨 적용한다.

> 호스트 venv에서 임시 운영하던 `python main.py btc watch` / `btc backfill`을
> K8s Pod로 옮기는 단계. API와 동일 이미지(`crypto-cti-api:phase-0`)를 그대로
> 재사용하고 command만 다르게 준다 (단일 이미지 + CMD override 패턴).

### 10.5.1 사전 점검

기존 호스트 프로세스가 살아있는지 확인 (PID 2040105 watch / 2021233 backfill 가능):

```bash
ps -ef | grep -E 'main\.py btc (watch|backfill)' | grep -v grep
```

원칙:
- **backfill이 진행 중이면 끝날 때까지 K8s 배포 보류** — 같은 height 범위를 두 곳에서
  처리하면 PK 충돌 + 중복 알림 발생.
- **watch는 마이그레이션 직전에만 종료** — 호스트 프로세스를 먼저 죽이고 K8s apply.

### 10.5.2 Secret에 WATCHLIST_WEBHOOK_URL 추가

현재 Discord webhook URL은 호스트 `.env`에만 존재. K8s Pod가 알림을 보내려면
`crypto-cti-env` Secret에 키를 추가해야 한다.

```bash
# 1) 현재 .env에서 webhook URL 추출 (gitignored 파일)
WEBHOOK_URL=$(grep '^WATCHLIST_WEBHOOK_URL=' /home/jimin/crypto-cti/crypto-python-cde/.env | cut -d= -f2-)
test -n "$WEBHOOK_URL" || { echo "ERROR: .env에 WATCHLIST_WEBHOOK_URL 없음"; exit 1; }

# 2) 기존 Secret을 그대로 두고 키만 patch (다른 키 유지)
kubectl patch secret crypto-cti-env -n crypto-cti \
  --type='json' \
  -p="[{\"op\":\"add\",\"path\":\"/data/WATCHLIST_WEBHOOK_URL\",\"value\":\"$(printf '%s' "$WEBHOOK_URL" | base64 -w0)\"}]"

# 3) 확인 (값은 base64 디코딩해서 비교)
kubectl get secret crypto-cti-env -n crypto-cti -o jsonpath='{.data.WATCHLIST_WEBHOOK_URL}' | base64 -d; echo
```

> 대안: `kubectl create secret generic crypto-cti-env --from-env-file=.env --dry-run=client -o yaml | kubectl apply -f -`
> 로 통째 재생성도 가능하지만, 다른 키(`API_KEYS` 등)가 .env에 빠져있으면 유실되니
> 위 patch 방식이 더 안전.

### 10.5.3 이미지 빌드 (재사용 시 생략 가능)

API Pod가 이미 사용 중인 `192.168.1.187:5000/crypto-cti-api:phase-0`를 그대로 사용한다
(단일 이미지 분기 — `command/args`만 다름). 코드 변경 없이 인덱서를 띄우는 것이 목적이라면
**빌드/푸시 단계 생략 가능**.

코드를 수정했다면 9번 섹션과 동일한 방법으로 재빌드:

```bash
cd /home/jimin/crypto-cti/crypto-python-cde
docker build -t 192.168.1.187:5000/crypto-cti-api:phase-0 .
docker push 192.168.1.187:5000/crypto-cti-api:phase-0

# 기존 API Pod도 새 이미지를 받도록 강제 재시작
kubectl rollout restart deployment/crypto-cti-api -n crypto-cti
```

### 10.5.4 watch 모드 배포

```bash
# 1) 호스트 watch 프로세스 종료 (있을 때만)
pkill -f 'main.py btc watch' || true

# 2) K8s watch 배포
kubectl apply -f /home/jimin/k8s-manifests/crypto-cti/phase-0/40-indexer-watch.yaml
kubectl rollout status deployment/crypto-cti-indexer-watch -n crypto-cti --timeout=120s

# 3) 로그로 ZMQ 구독 확인
kubectl -n crypto-cti logs -l app=crypto-cti-indexer-watch -f --tail=50
```

검증 포인트 (로그):
- `Starting real-time block watch via ZMQ` 메시지
- `ZMQ connected to tcp://bitcoind.crypto-cti.svc.cluster.local:28332` (또는 동등)
- 평균 10분 이내 새 블록 수신 → `block <height> processed` 류 로그

### 10.5.5 backfill Job 실행

`41-indexer-backfill-job.yaml.tmpl`은 `__START__` / `__END__` placeholder 포함 템플릿.
`sed`로 치환 후 apply.

```bash
# 예: 942330 ~ 947939 범위 backfill
START=942330
END=947939

sed -e "s/__START__/${START}/g" -e "s/__END__/${END}/g" \
  /home/jimin/k8s-manifests/crypto-cti/phase-0/41-indexer-backfill-job.yaml.tmpl \
  | kubectl apply -f -

# 진행 로그
kubectl -n crypto-cti logs -l job-name=indexer-backfill-${START}-${END} -f

# 완료 대기
kubectl wait --for=condition=complete job/indexer-backfill-${START}-${END} \
  -n crypto-cti --timeout=3600s
```

> pruned 노드 한계: `START`가 `bitcoind getblockchaininfo`의 `pruneheight` 미만이면
> RPC가 실패. 사전에 확인 (섹션 7).

> Job은 `ttlSecondsAfterFinished=3600`이라 완료 1시간 후 자동 삭제.
> 로그를 보존하려면 위 wait 후 즉시 `kubectl logs` 또는 외부 로그 수집기로 옮길 것.

### 10.5.6 마이그레이션 체크리스트

- [ ] 호스트 backfill 프로세스(PID 2021233 등) 종료 또는 자연 종료 대기
- [ ] 호스트 watch 프로세스(PID 2040105 등) `pkill` 종료
- [ ] `WATCHLIST_WEBHOOK_URL` Secret 추가 확인
- [ ] `kubectl apply -f 40-indexer-watch.yaml`
- [ ] watch Pod에서 ZMQ 연결 + 새 블록 수신 로그 확인 (10~15분 관찰)
- [ ] Discord 채널에서 테스트 watchlist 주소로 알림 수신 확인
- [ ] 호스트 venv `.env`는 디버그 용도로만 보관 (port-forward 경로 — 섹션 10)

---

## 11. 롤백

```bash
# 부분 롤백
# indexer (watch/backfill) — 호스트 venv로 임시 복귀하려면 먼저 K8s Pod 제거
kubectl delete -f /home/jimin/k8s-manifests/crypto-cti/phase-0/40-indexer-watch.yaml --ignore-not-found
kubectl delete job -n crypto-cti -l app=crypto-cti-indexer-backfill --ignore-not-found

kubectl delete -f /home/jimin/k8s-manifests/crypto-cti/phase-0/30-api.yaml
kubectl delete -f /home/jimin/k8s-manifests/crypto-cti/phase-0/20-bitcoind.yaml
kubectl delete -f /home/jimin/k8s-manifests/crypto-cti/phase-0/10-postgres.yaml
kubectl delete pvc -l app=postgres -n crypto-cti
kubectl delete pvc -l app=bitcoind -n crypto-cti

# 전체 제거
kubectl delete namespace crypto-cti

# StorageClass 제거 (다른 워크로드가 안 쓸 때만)
kubectl delete -f /home/jimin/k8s-manifests/storage/local-path-provisioner.yaml

# local-path 데이터 잔여물 삭제 (각 노드에서)
# sudo rm -rf /mnt/data/local-path-provisioner
```
