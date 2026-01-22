# Canary 배포 + HA 전략 (Istio + Argo Rollouts)

> Canary 배포 시에도 Pod 수를 유지하면서 HA를 보장하는 전략

**작성일**: 2026-01-22
**상태**: ✅ 적용 완료

---

## 목차

1. [문제 상황](#문제-상황)
2. [해결 방안 분석](#해결-방안-분석)
3. [최종 설계](#최종-설계)
4. [적용 결과](#적용-결과)
5. [관련 설정](#관련-설정)

---

## 문제 상황

### 초기 요구사항

```
✅ HA (고가용성): Pod를 여러 노드에 분산 배치
✅ Canary 배포: 점진적 트래픽 전환
✅ 리소스 효율: 불필요한 Pod 증가 방지
```

### 충돌 발생

**topologySpreadConstraints + DoNotSchedule + Canary 배포**를 함께 사용하면 충돌 발생:

```
┌─────────────────────────────────────────────────────────────┐
│ 문제 상황: Canary 배포 시 Pod Pending                        │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  replicas: 2                                                │
│  topologySpread: DoNotSchedule (노드당 1개만)               │
│                                                             │
│  배포 전:                                                   │
│  ┌─────────────┐    ┌─────────────┐                        │
│  │ k8s-worker1 │    │ k8s-worker2 │                        │
│  │  stable #1  │    │  stable #2  │                        │
│  └─────────────┘    └─────────────┘                        │
│                                                             │
│  Canary 배포 시도 (기존 방식):                              │
│  ┌─────────────┐    ┌─────────────┐                        │
│  │ k8s-worker1 │    │ k8s-worker2 │                        │
│  │  stable #1  │    │  stable #2  │                        │
│  │  canary #1  │    │  canary #2  │  ← Pending!            │
│  │  (Pending!) │    │  (Pending!) │                        │
│  └─────────────┘    └─────────────┘                        │
│                                                             │
│  → DoNotSchedule: 노드당 1개만 허용                         │
│  → canary Pod 스케줄 불가                                   │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 기존 해결 시도

| 방법 | 결과 | 문제점 |
|------|------|--------|
| **ScheduleAnyway (soft)** | 배포 성공 | HA 미보장 (같은 노드에 몰릴 수 있음) |
| **DoNotSchedule (hard)** | 배포 실패 | Canary Pod Pending |

---

## 해결 방안 분석

### 핵심 인사이트: Istio Traffic Routing

**AWS ALB와 동일한 방식**으로 Istio가 트래픽을 분배:

```
┌─────────────────────────────────────────────────────────────┐
│ Istio VirtualService Traffic Routing                        │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  VirtualService weight 설정:                                │
│    - stable: 90%                                            │
│    - canary: 10%                                            │
│                                                             │
│  트래픽 흐름:                                                │
│  ┌─────────────┐                                            │
│  │   Client    │                                            │
│  └──────┬──────┘                                            │
│         │ 100% traffic                                      │
│         ▼                                                   │
│  ┌─────────────┐                                            │
│  │   Istio     │                                            │
│  │   Gateway   │                                            │
│  └──────┬──────┘                                            │
│         │                                                   │
│    ┌────┴────┐                                              │
│    │  90%    │  10%                                         │
│    ▼         ▼                                              │
│ ┌──────┐  ┌──────┐                                          │
│ │stable│  │canary│                                          │
│ │ Pod  │  │ Pod  │                                          │
│ └──────┘  └──────┘                                          │
│                                                             │
│ → Pod 개수와 무관하게 트래픽 비율 조절 가능!                │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### Pod 개수 vs 트래픽 비율

| 관점 | 일반 Kubernetes | Istio Traffic Routing |
|------|-----------------|----------------------|
| **트래픽 분배** | Pod 개수에 비례 | VirtualService weight |
| **Canary 10%** | canary 1개, stable 9개 필요 | canary 1개면 충분 |
| **리소스** | 많은 Pod 필요 | 최소 Pod로 가능 |

### 왜 Pod 2개를 유지해야 하나?

트래픽 라우팅은 1개로 충분하지만, **다른 이유로 2개 필요**:

| 이유 | 설명 |
|------|------|
| **HA (고가용성)** | Pod 1개 죽어도 서비스 유지 |
| **HPA 스케일링** | 트래픽 증가 시 확장 가능 |
| **노드 장애 대응** | 각 노드에 1개씩 분산 |

---

## 최종 설계

### dynamicStableScale: true

Argo Rollouts의 `dynamicStableScale` 옵션으로 해결:

```yaml
strategy:
  canary:
    dynamicStableScale: true  # ← 핵심 설정
    trafficRouting:
      istio:
        virtualService: ...
```

### 동작 방식

```
┌─────────────────────────────────────────────────────────────┐
│ dynamicStableScale: true 동작                               │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  replicas: 2                                                │
│  topologySpread: DoNotSchedule                              │
│                                                             │
│  배포 전:                                                   │
│  ┌─────────────┐    ┌─────────────┐                        │
│  │ k8s-worker1 │    │ k8s-worker2 │                        │
│  │  stable #1  │    │  stable #2  │     총 2개             │
│  └─────────────┘    └─────────────┘                        │
│                                                             │
│  10% Canary:                                                │
│  ┌─────────────┐    ┌─────────────┐                        │
│  │ k8s-worker1 │    │ k8s-worker2 │                        │
│  │  stable #1  │    │  canary #1  │     총 2개 유지!       │
│  │    (90%)    │    │    (10%)    │                        │
│  └─────────────┘    └─────────────┘                        │
│                                                             │
│  50% Canary:                                                │
│  ┌─────────────┐    ┌─────────────┐                        │
│  │ k8s-worker1 │    │ k8s-worker2 │                        │
│  │  stable #1  │    │  canary #1  │     총 2개 유지!       │
│  │    (50%)    │    │    (50%)    │                        │
│  └─────────────┘    └─────────────┘                        │
│                                                             │
│  100% (완료):                                               │
│  ┌─────────────┐    ┌─────────────┐                        │
│  │ k8s-worker1 │    │ k8s-worker2 │                        │
│  │  stable #1  │    │  stable #2  │     총 2개             │
│  │ (new ver)   │    │ (new ver)   │                        │
│  └─────────────┘    └─────────────┘                        │
│                                                             │
│  → Canary 배포 중에도 총 Pod 수 2개 유지!                   │
│  → DoNotSchedule 제약 충돌 없음!                            │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### HPA와의 관계

```
┌─────────────────────────────────────────────────────────────┐
│ Pod 증가 허용 여부                                          │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ✅ HPA/VPA로 인한 증가 → OK                                │
│     평소 2개 → 트래픽 증가 → 4개, 6개...                    │
│     (실제 부하 대응)                                        │
│                                                             │
│  ❌ Canary로 인한 증가 → NOT OK                             │
│     stable 2 + canary 2 = 4개                               │
│     (불필요한 리소스 낭비)                                  │
│                                                             │
│  ✅ dynamicStableScale로 해결!                              │
│     Canary 시에도 2개 유지                                  │
│     Istio가 트래픽 분배                                     │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 적용 결과

### 변경 사항

| 파일 | 변경 내용 |
|------|----------|
| `web-rollout.yaml` | `dynamicStableScale: true` 추가, `DoNotSchedule` 적용 |
| `was-rollout.yaml` | `dynamicStableScale: true` 추가, `DoNotSchedule` 적용 |

### 최종 설정

**WEB Rollout:**
```yaml
spec:
  replicas: 2
  strategy:
    canary:
      dynamicStableScale: true  # ← Pod 수 유지
      trafficRouting:
        istio:
          virtualService:
            name: web-vsvc
          destinationRule:
            name: web-dest-rule
      steps:
        - setWeight: 10
        - pause: {duration: 30s}
        - setWeight: 50
        - pause: {duration: 30s}
        - setWeight: 90
        - pause: {duration: 30s}
        - setWeight: 100
  template:
    spec:
      topologySpreadConstraints:
        - maxSkew: 1
          topologyKey: kubernetes.io/hostname
          whenUnsatisfiable: DoNotSchedule  # ← HA 보장
          labelSelector:
            matchLabels:
              app: web
```

**WAS Rollout:**
```yaml
spec:
  replicas: 2  # HPA가 2-10으로 조정
  strategy:
    canary:
      dynamicStableScale: true  # ← Pod 수 유지
      trafficRouting:
        istio:
          virtualService:
            name: was-retry-timeout
          destinationRule:
            name: was-dest-rule
      steps:
        - setWeight: 20
        - pause: {duration: 1m}
        - setWeight: 50
        - pause: {duration: 1m}
        - setWeight: 80
        - pause: {duration: 1m}
  template:
    spec:
      topologySpreadConstraints:
        - maxSkew: 1
          topologyKey: kubernetes.io/hostname
          whenUnsatisfiable: DoNotSchedule  # ← HA 보장
          labelSelector:
            matchLabels:
              app: was
```

### 달성된 목표

| 목표 | 상태 | 방법 |
|------|------|------|
| **HA 보장** | ✅ | `DoNotSchedule` - 노드별 분산 강제 |
| **Canary 배포** | ✅ | Istio Traffic Routing |
| **Pod 수 유지** | ✅ | `dynamicStableScale: true` |
| **HPA 호환** | ✅ | 트래픽 증가 시 정상 스케일 |

---

## 관련 설정

### Istio Ingress Gateway HA

Istio Ingress Gateway는 Canary가 아닌 일반 Deployment이므로 직접 설정:

```bash
kubectl patch deployment istio-ingressgateway -n istio-system --type='strategic' -p='{
  "spec": {
    "replicas": 2,
    "strategy": {
      "rollingUpdate": {
        "maxUnavailable": 1,
        "maxSurge": 0
      }
    },
    "template": {
      "spec": {
        "topologySpreadConstraints": [
          {
            "maxSkew": 1,
            "topologyKey": "kubernetes.io/hostname",
            "whenUnsatisfiable": "DoNotSchedule",
            "labelSelector": {
              "matchLabels": {
                "app": "istio-ingressgateway"
              }
            }
          }
        ]
      }
    }
  }
}'
```

### 현재 Pod 분포 확인

```bash
# Istio Ingress Gateway
kubectl get pods -n istio-system -l app=istio-ingressgateway -o wide

# WEB
kubectl get pods -n blog-system -l app=web -o wide

# WAS
kubectl get pods -n blog-system -l app=was -o wide
```

---

## 트러블슈팅

### Canary Pod이 Pending인 경우

**원인:** `dynamicStableScale: true` 미설정 또는 Istio trafficRouting 미설정

**확인:**
```bash
kubectl get rollout web -n blog-system -o yaml | grep dynamicStableScale
kubectl get rollout was -n blog-system -o yaml | grep dynamicStableScale
```

**해결:** rollout 파일에 `dynamicStableScale: true` 추가

### 롤아웃 상태 확인

```bash
kubectl argo rollouts status web -n blog-system
kubectl argo rollouts status was -n blog-system
```

---

## 요약

```
┌─────────────────────────────────────────────────────────────┐
│ 최종 아키텍처                                               │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Istio Traffic Routing + dynamicStableScale + DoNotSchedule │
│                                                             │
│  = Canary 배포 시에도 Pod 수 유지 (2개)                     │
│  = HA 보장 (노드별 분산)                                    │
│  = HPA로 트래픽 대응 가능                                   │
│  = 리소스 효율적 사용                                       │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

**작성:** Claude Code
**커밋:** d4897dd (feat: Enable dynamicStableScale + DoNotSchedule for HA Canary)
