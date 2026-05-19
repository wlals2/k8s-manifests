# _archive_k8s — 보류된 K8s indexer manifest

## 보류 사유 (2026-05-05)

BTC indexer를 K8s Pod로 옮기는 대신 **호스트 docker 컨테이너로 단순 운영**하기로 결정.
이유:
- 호스트가 K8s control plane(`k8s-cp`)이라 kube-proxy iptables를 통해 ClusterIP에
  직접 접근 가능 → `--network host`로 `.env`의 ClusterIP 그대로 재사용
- 인덱서 1개 워크로드에 K8s 추가 복잡도(Deployment/Job/Secret 동기화 등) 불필요
- 운영자 1인 환경이라 `docker run` 수준의 단순함 우선

현재 운영 런타임: **docker.io 28.2.2** (k8s-cp 호스트, systemd enable)
현재 운영: [`../docker/`](../docker/) (run-watch.sh / run-backfill.sh / README.md).

## 보관 대상

- `40-indexer-watch.yaml` — Deployment + Service (watch 모드 상시 실행)
- `41-indexer-backfill-job.yaml.tmpl` — Job 템플릿 (sed 치환 후 apply)

## 다시 K8s로 옮길 때

조건이 바뀌어 K8s로 마이그레이션이 필요해지는 경우 (예: 노드 분산, 자동 복구,
GitLab CI/CD 연동 등):

1. 위 두 파일을 `phase-0/`로 이동
2. `phase-0/APPLY.md` §10.5 절차 그대로 적용
3. 호스트 docker 컨테이너 종료(`docker stop crypto-cti-watch`)
4. Secret patch (`WATCHLIST_WEBHOOK_URL`) — APPLY.md §10.5.2 참조

manifest 자체는 SSoT 위반 없이 보존됨.
