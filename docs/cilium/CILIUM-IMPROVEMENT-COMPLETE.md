# Cilium 개선 작업 완료 보고서

> **작업일**: 2026-01-14
> **클러스터**: local-k8s (3 노드)
> **Cilium 버전**: v1.18.4

---

## ✅ 완료된 작업

### 1. Hubble Relay & UI 설치 ✅

**목적**: 네트워크 플로우 시각화 및 실시간 모니터링

**설치 내용**:
- ✅ **Hubble Relay**: 1 replica (Running)
- ✅ **Hubble UI**: 1 replica (Running)
- ✅ **Hubble CLI**: v1.18.5 설치 완료

**접속 정보**:
```
Hubble UI (웹 대시보드):
- http://192.168.1.187:31234 (k8s-cp)
- http://192.168.1.61:31234 (k8s-worker1)
- http://192.168.1.62:31234 (k8s-worker2)

Hubble CLI:
hubble observe --server localhost:4245
```

**검증 결과**:
```bash
$ hubble observe --last 10
Jan 14 10:19:43.212: longhorn-system/csi-provisioner -> kube-apiserver
Jan 14 10:19:44.726: coredns -> kube-apiserver
Jan 14 10:19:45.526: hubble-relay -> cilium-agent (3 nodes)
...
```

✅ 네트워크 플로우가 정상적으로 수집되고 있습니다!

---

## 🔍 검토 중인 작업

### 2. kube-proxy 대체 (선택사항)

**현재 상태**:
- kube-proxy: ✅ Running (3 pods)
- kube-proxy-replacement: **false** (비활성화)

**kube-proxy 대체란?**

Cilium이 kube-proxy의 역할을 eBPF로 대체하여 성능을 향상시킵니다.

**비교**:

| 항목 | kube-proxy (현재) | Cilium eBPF (대체 시) |
|------|------------------|----------------------|
| **구현** | iptables 규칙 | eBPF 프로그램 |
| **성능** | 보통 | **30-40% 빠름** |
| **Latency** | 보통 | **30% 감소** |
| **CPU 사용량** | 보통 | **낮음** |
| **Service 타입** | ClusterIP, NodePort, LoadBalancer | 모두 지원 + DSR |
| **복잡도** | 낮음 | 중간 |
| **안정성** | 매우 높음 | 높음 (프로덕션 검증됨) |

---

### 장점 ✅

1. **성능 향상**:
   - Throughput: 30-40% 증가
   - Latency: 30% 감소
   - CPU 사용량 감소

2. **iptables 규칙 제거**:
   - 수천 개의 iptables 규칙 → eBPF 프로그램
   - iptables chain 순회 오버헤드 제거

3. **DSR (Direct Server Return)**:
   - LoadBalancer에서 응답 패킷이 바로 클라이언트로 전송
   - ALB/NLB 성능 향상

4. **kube-proxy Pod 제거**:
   - 리소스 절약 (3 pods × CPU/Memory)

---

### 단점 ❌

1. **복잡도 증가**:
   - iptables → eBPF (디버깅 어려움)
   - 트러블슈팅 시 eBPF 지식 필요

2. **호환성 문제 가능성**:
   - 일부 특수한 네트워크 설정과 충돌 가능
   - ExternalTrafficPolicy: Local 등 일부 기능 제약

3. **롤백 어려움**:
   - 활성화 후 문제 발생 시 롤백 복잡
   - 서비스 중단 가능

4. **로컬 클러스터 특성**:
   - 프로덕션이 아닌 실험 환경
   - 성능보다 안정성이 중요할 수 있음

---

### 권장 사항 📋

**현재 로컬 클러스터 환경**:
- 3노드 클러스터 (homelab)
- 실험 및 학습 목적
- 프로덕션 트래픽 없음

**권장**: ⚠️ **단계적 접근**

#### Option 1: 현재 상태 유지 (권장)

**이유**:
- ✅ kube-proxy는 안정적으로 작동 중
- ✅ Hubble UI/Relay로 충분한 개선 완료
- ✅ 불필요한 리스크 회피

**적합한 경우**:
- 안정성이 우선
- 성능 문제가 없음
- 학습 중심 환경

---

#### Option 2: 테스트 환경에서 먼저 시도

**단계**:

1. **백업**:
   ```bash
   # 현재 Cilium 설정 백업
   helm get values cilium -n kube-system > cilium-values-backup.yaml
   ```

2. **kube-proxy 대체 활성화**:
   ```bash
   helm upgrade cilium cilium/cilium --version 1.18.4 \
     --namespace kube-system \
     --reuse-values \
     --set kubeProxyReplacement=true \
     --set k8sServiceHost=192.168.1.187 \
     --set k8sServicePort=6443
   ```

3. **kube-proxy 중지**:
   ```bash
   kubectl delete ds kube-proxy -n kube-system
   ```

4. **검증**:
   ```bash
   # Service 접근 테스트
   kubectl get svc -A
   kubectl run test --image=nginx --port=80
   kubectl expose pod test --port=80 --type=NodePort
   curl <NodeIP>:<NodePort>
   ```

5. **문제 발생 시 롤백**:
   ```bash
   helm upgrade cilium cilium/cilium --version 1.18.4 \
     --namespace kube-system \
     --reuse-values \
     --set kubeProxyReplacement=false

   # kube-proxy 재시작
   kubectl apply -f /etc/kubernetes/manifests/kube-proxy.yaml
   ```

---

#### Option 3: 금융권/프로덕션 환경 (향후 참고)

**프로덕션 도입 시 고려사항**:

1. **Canary 배포**:
   - 일부 노드에서만 먼저 테스트
   - 트래픽 일부만 전환

2. **충분한 테스트**:
   - LoadBalancer, NodePort, ClusterIP 모두 테스트
   - ExternalTrafficPolicy, Session Affinity 테스트

3. **모니터링 강화**:
   - Cilium 메트릭 모니터링
   - Service 응답 시간 추적

4. **롤백 계획**:
   - 명확한 롤백 절차
   - 긴급 상황 대응 계획

---

## 📊 개선 결과 요약

### Before (개선 전)

| 항목 | 상태 |
|------|------|
| **Cilium** | v1.18.4 (Agent, Envoy, Operator) |
| **Hubble** | ConfigMap에서 활성화 (Pod 없음) |
| **관측성** | 제한적 |
| **kube-proxy** | 사용 중 |

---

### After (개선 후)

| 항목 | 상태 | 개선 효과 |
|------|------|----------|
| **Cilium** | v1.18.4 | 동일 |
| **Hubble Relay** | ✅ Running (1 replica) | 네트워크 플로우 수집 |
| **Hubble UI** | ✅ Running (http://192.168.1.187:31234) | 웹 대시보드 |
| **Hubble CLI** | ✅ v1.18.5 설치 | CLI로 네트워크 플로우 조회 |
| **관측성** | 🔥 **대폭 향상** | 실시간 네트워크 모니터링 |
| **kube-proxy** | 사용 중 (대체 검토 중) | 안정성 우선 |

---

## 🎯 Hubble 활용 가이드

### 1. Hubble UI 웹 대시보드

**접속**: http://192.168.1.187:31234

**기능**:
- ✅ Service Dependency Map (어떤 Pod가 어디에 연결되는지)
- ✅ 네트워크 플로우 실시간 시각화
- ✅ 거부된 트래픽 확인 (보안 이벤트)
- ✅ L7 HTTP 트래픽 분석

**사용 예시**:
1. 특정 Namespace 선택 (예: kube-system)
2. Service Dependency Map 확인
3. 플로우 리스트에서 DROP된 트래픽 확인

---

### 2. Hubble CLI 명령어

**기본 조회**:
```bash
# 실시간 네트워크 플로우 모니터링
hubble observe

# 최근 50개 플로우
hubble observe --last 50

# 특정 Namespace만
hubble observe --namespace kube-system

# 특정 Pod만
hubble observe --pod cilium-ksv4c
```

**보안 이벤트 조회**:
```bash
# 거부된 트래픽만 (보안 중요!)
hubble observe --verdict DROPPED

# 특정 시간대 이벤트
hubble observe --since 2026-01-14T00:00:00Z
```

**L7 트래픽 분석**:
```bash
# HTTP 트래픽만
hubble observe --protocol http

# DNS 쿼리만
hubble observe --protocol dns

# TCP 연결만
hubble observe --type trace:to-endpoint
```

**Service Dependency**:
```bash
# Service Map JSON 출력
hubble observe --output json | jq '.flow'
```

---

### 3. 금융권 감사 로그 활용

**시나리오**: 금융감독원 감사 시 네트워크 트래픽 증빙

**감사 로그 수집**:
```bash
# 1월 전체 로그 내보내기
hubble observe --since 2026-01-01T00:00:00Z \
  --until 2026-01-31T23:59:59Z \
  --output json > audit-log-jan-2026.json

# 거부된 트래픽만 (보안 이벤트)
hubble observe --verdict DROPPED \
  --since 2026-01-01T00:00:00Z \
  --output json > security-events-jan-2026.json
```

**감사 리포트 생성**:
```bash
# 거부된 트래픽 통계
jq -r '.flow | select(.verdict == "DROPPED") | "\(.time) \(.source.pod_name) -> \(.destination.pod_name) (\(.l7.http.method) \(.l7.http.url))"' audit-log.json
```

---

## 📚 참고 문서

| 문서 | 위치 |
|------|------|
| **LOCAL-K8S-CILIUM-ARCHITECTURE.md** | ~/LOCAL-K8S-CILIUM-ARCHITECTURE.md |
| **CILIUM-ENTERPRISE-USE-CASES.md** | ~/CILIUM-ENTERPRISE-USE-CASES.md |
| **MD-FILES-STATUS-REPORT.md** | ~/MD-FILES-STATUS-REPORT.md |
| **Cilium Helm Values** | ~/cilium-values-hubble.yaml |

---

## 🚀 다음 단계 (선택)

### 1. Hubble UI 접속 및 탐색 ✅
```bash
# 브라우저에서 접속
http://192.168.1.187:31234
```

### 2. NetworkPolicy 테스트 (선택)
```yaml
# 예시: default namespace의 Pod 간 통신 차단
apiVersion: cilium.io/v2
kind: CiliumNetworkPolicy
metadata:
  name: deny-all
  namespace: default
spec:
  endpointSelector: {}
  ingress: []
  egress: []
```

### 3. kube-proxy 대체 (선택, 신중하게)
- Option 1: 현재 상태 유지 (권장)
- Option 2: 테스트 환경에서 시도
- Option 3: 프로덕션 도입 (향후)

---

## ✅ 최종 체크리스트

- [x] Worker 노드 복구 확인
- [x] MD 파일 상태 검증
- [x] Hubble Relay 설치
- [x] Hubble UI 설치 및 접속 확인
- [x] Hubble CLI 설치
- [x] 네트워크 플로우 수집 검증
- [x] kube-proxy 대체 옵션 검토
- [ ] Hubble UI 웹 대시보드 탐색 (사용자)
- [ ] kube-proxy 대체 결정 (사용자)

---

**작성일**: 2026-01-14
**작성자**: Claude (with Jimin)
**버전**: 1.0
