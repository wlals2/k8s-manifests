# Blog System Autoscaling 완전 가이드

> HPA + VPA 이중 오토스케일링 구성
>
> **프로젝트 목표**: 트래픽 증가 시 자동 스케일링 + 리소스 최적화

**최종 업데이트:** 2026-01-22
**문서 버전:** 1.0
**시스템 상태:** ✅ 운영 중

---

## 📋 목차

1. [프로젝트 개요](#프로젝트-개요)
2. [왜 이렇게 구축했는가](#왜-이렇게-구축했는가)
3. [HPA 상세 구성](#hpa-상세-구성)
4. [VPA 상세 구성](#vpa-상세-구성)
5. [Grafana 대시보드](#grafana-대시보드)
6. [실제 시나리오](#실제-시나리오)
7. [트러블슈팅](#트러블슈팅)
8. [다음 단계](#다음-단계)

---

## 프로젝트 개요

### 무엇을 만들었는가?

**HPA (Horizontal Pod Autoscaler)** + **VPA (Vertical Pod Autoscaler)**를 조합한 이중 오토스케일링 시스템

**주요 특징:**
- ✅ Multi-Metric HPA: CPU + Network 트래픽 기반 스케일링
- ✅ VPA Off 모드: 권장 리소스 값만 제공 (자동 적용 안 함)
- ✅ Grafana 대시보드: 실시간 HPA 상태 모니터링
- ✅ ArgoCD 통합: GitOps 방식으로 관리

### 시스템 규모

| 항목 | WAS | WEB |
|------|-----|-----|
| **Min Replicas** | 2 | 2 |
| **Max Replicas** | 10 | 5 |
| **CPU 임계값** | 70% | 60% |
| **Network 임계값** | 100 KB/s | 300 KB/s |
| **Scale Down 대기** | 5분 | 5분 |
| **Scale Up 대기** | 1분 | 1분 |

### 아키텍처 개요

```
┌─────────────────────────────────────────────────────────────────┐
│                    Autoscaling Stack                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐        │
│  │ Prometheus  │───▶│  Prometheus │───▶│     HPA     │        │
│  │  (Metrics)  │    │   Adapter   │    │ (Scaler)    │        │
│  └─────────────┘    └─────────────┘    └──────┬──────┘        │
│        │                                       │               │
│        │            Custom Metrics API         │               │
│        │         (cpu, network bytes)          │               │
│        │                                       ▼               │
│        │                              ┌─────────────┐          │
│        │                              │   Rollout   │          │
│        │                              │  (WAS/WEB)  │          │
│        │                              └─────────────┘          │
│        │                                       ▲               │
│        ▼                                       │               │
│  ┌─────────────┐                      ┌───────┴──────┐        │
│  │   Grafana   │                      │     VPA      │        │
│  │ (Dashboard) │                      │ (Recommender)│        │
│  └─────────────┘                      └──────────────┘        │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 왜 이렇게 구축했는가?

### 1. 왜 Multi-Metric HPA를 선택했는가?

**선택한 방식: CPU + Network 이중 메트릭**

#### 대안 분석

| 방식 | 장점 | 단점 | 선택 이유 |
|------|------|------|----------|
| **CPU + Network** | 트래픽 급증 조기 감지<br>CPU 부하 전 스케일링 | 설정 복잡 | ✅ **선택** |
| CPU만 사용 | 간단함 | 네트워크 급증 시 지연 | ❌ 반응 느림 |
| 커스텀 메트릭만 | 정밀한 제어 | Prometheus Adapter 필수 | ❌ 복잡도 증가 |
| Istio 메트릭 | 요청 기반 정확 | Istio 의존성 | ❌ 추후 고려 |

#### 선택 이유 (Why Multi-Metric?)

1. **OR 조건 스케일링**: 둘 중 하나라도 임계값 초과 시 즉시 스케일 아웃
   ```
   CPU 70% 초과    OR   Network 100KB/s 초과
         │                    │
         └────────┬───────────┘
                  ▼
            Scale Out!
   ```

2. **네트워크 급증 조기 감지**: CPU는 정상이지만 요청이 급증하는 경우 대응
   - Before: CPU 부하까지 기다려야 스케일링
   - After: 네트워크 트래픽 급증 시 즉시 스케일링

3. **cAdvisor 메트릭 활용**: 별도 설치 없이 기존 인프라 활용
   ```
   container_network_receive_bytes_total  # 이미 수집 중
   ```

#### 트레이드오프

**단점:**
- ❌ Prometheus Adapter 설정 필요
- ❌ 메트릭 이름 변환 규칙 이해 필요

**하지만:**
- ✅ 한 번 설정하면 자동 운영
- ✅ 트래픽 급증 시 빠른 대응
- ✅ 기존 모니터링 인프라 재사용

---

### 2. 왜 VPA는 Off 모드로 설정했는가?

**선택한 방식: VPA updateMode: Off**

#### 대안 분석

| 모드 | 작동 방식 | 장점 | 단점 | 선택 이유 |
|------|----------|------|------|----------|
| **Off** | 권장 값만 제공 | 안정적<br>수동 제어 | 자동화 없음 | ✅ **선택** |
| Auto | Pod 재시작하며 적용 | 완전 자동화 | 서비스 중단 위험 | ❌ 위험 |
| Recreate | 수동 재시작 시 적용 | 중간 수준 | 반자동 | ❌ 복잡 |

#### 선택 이유 (Why Off Mode?)

1. **HPA와의 충돌 방지**
   ```
   HPA: "CPU 70% 초과, 스케일 아웃!"
   VPA: "requests 증가, Pod 재시작!"  ← 충돌 위험

   해결: VPA Off → 권장 값만 제공, 적용은 수동
   ```

2. **서비스 안정성 우선**
   - VPA Auto는 Pod을 재시작함 → 순간적 서비스 중단
   - 최소 2 replicas 유지하지만, 동시 재시작 가능성 존재

3. **권장 값 참고 용도**
   ```bash
   # VPA 권장 값 확인
   kubectl describe vpa was-vpa -n blog-system

   # 출력 예:
   # Lower Bound:  cpu: 150m, memory: 300Mi
   # Target:       cpu: 200m, memory: 400Mi  ← 이 값 참고
   # Upper Bound:  cpu: 300m, memory: 600Mi
   ```

---

### 3. 왜 이 임계값을 선택했는가?

#### WAS: CPU 70%, Network 100KB/s

| 설정 | 값 | 이유 |
|------|-----|------|
| **CPU 임계값** | 70% | Spring Boot JIT 컴파일 여유<br>Heap GC 버퍼 확보 |
| **Network 임계값** | 100KB/s | 평균 응답 2KB × 50 req/s |
| **Max Replicas** | 10 | 백엔드 확장성 확보 |

#### WEB: CPU 60%, Network 300KB/s

| 설정 | 값 | 이유 |
|------|-----|------|
| **CPU 임계값** | 60% | Nginx 경량, 낮은 임계값으로 빠른 대응 |
| **Network 임계값** | 300KB/s | 정적 파일 서빙, 큰 응답 크기 |
| **Max Replicas** | 5 | 프론트엔드는 적은 replica로 충분 |

---

## HPA 상세 구성

### 파일 위치

```
/home/jimin/k8s-manifests/blog-system/hpa.yaml
```

### WAS HPA 설정

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: was-hpa
  namespace: blog-system
spec:
  scaleTargetRef:
    apiVersion: argoproj.io/v1alpha1
    kind: Rollout
    name: was

  minReplicas: 2
  maxReplicas: 10

  metrics:
  # Metric 1: CPU (Resource 메트릭)
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70

  # Metric 2: Network (Custom 메트릭)
  - type: Pods
    pods:
      metric:
        name: container_network_receive_bytes_per_second
      target:
        type: AverageValue
        averageValue: 100k

  behavior:
    scaleDown:
      stabilizationWindowSeconds: 300  # 5분 대기
      policies:
      - type: Percent
        value: 50           # 50%씩 감소
        periodSeconds: 60
    scaleUp:
      stabilizationWindowSeconds: 60   # 1분 대기
      policies:
      - type: Percent
        value: 100          # 100%씩 증가 (2배)
        periodSeconds: 60
```

### HPA 확인 명령어

```bash
# HPA 상태 확인
kubectl get hpa -n blog-system

# 상세 정보 (메트릭 값 포함)
kubectl describe hpa was-hpa -n blog-system

# 예상 출력:
# Metrics:                                               ( current / target )
#   resource cpu on pods  (as a percentage of request):  23% (58m) / 70%
#   "container_network_receive_bytes_per_second":        12345 / 100k
```

---

## VPA 상세 구성

### 파일 위치

```
/home/jimin/k8s-manifests/blog-system/vpa.yaml
```

### WAS VPA 설정

```yaml
apiVersion: autoscaling.k8s.io/v1
kind: VerticalPodAutoscaler
metadata:
  name: was-vpa
  namespace: blog-system
spec:
  targetRef:
    apiVersion: argoproj.io/v1alpha1
    kind: Rollout
    name: was

  updatePolicy:
    updateMode: "Off"  # 권장 값만 제공

  resourcePolicy:
    containerPolicies:
    - containerName: spring-boot
      minAllowed:
        cpu: 100m
        memory: 256Mi
      maxAllowed:
        cpu: 1000m
        memory: 2Gi
      controlledResources:
      - cpu
      - memory
```

### VPA 권장 값 확인

```bash
# VPA 권장 값 조회
kubectl describe vpa was-vpa -n blog-system | grep -A10 "Recommendation"

# 출력 예:
# Recommendation:
#   Container Recommendations:
#     Container Name:  spring-boot
#     Lower Bound:
#       Cpu:     150m
#       Memory:  300Mi
#     Target:           ← 권장 값
#       Cpu:     200m
#       Memory:  450Mi
#     Upper Bound:
#       Cpu:     400m
#       Memory:  800Mi
```

---

## Grafana 대시보드

### 대시보드 정보

| 항목 | 값 |
|------|-----|
| **이름** | Blog System HPA Monitoring |
| **UID** | blog-hpa-monitoring |
| **자동 로드** | grafana_dashboard: "1" label |
| **새로고침** | 10초 |

### 패널 구성

```
┌─────────────────────────────────┬─────────────────────────────────┐
│  1. HPA Replicas               │  2. WAS Current Replicas        │
│     (Current vs Desired)       │     (Gauge)                     │
│     [Time Series]              │                                 │
├─────────────────────────────────┼─────────────────────────────────┤
│  3. WAS CPU Utilization (%)    │  4. WAS Network Receive Rate    │
│     [Time Series]              │     [Time Series]               │
├─────────────────────────────────┼─────────────────────────────────┤
│  5. WEB CPU Utilization (%)    │  6. WEB Network Receive Rate    │
│     [Time Series]              │     [Time Series]               │
├─────────────────────────────────────────────────────────────────────┤
│  7. HPA Status Conditions (Table)                                  │
│     - ScalingActive, AbleToScale, ScalingLimited                   │
└─────────────────────────────────────────────────────────────────────┘
```

### 주요 PromQL 쿼리

#### Panel 1: HPA Replicas

```promql
# Current Replicas
kube_horizontalpodautoscaler_status_current_replicas{namespace="blog-system"}

# Desired Replicas
kube_horizontalpodautoscaler_status_desired_replicas{namespace="blog-system"}

# Min/Max 범위
kube_horizontalpodautoscaler_spec_min_replicas{namespace="blog-system"}
kube_horizontalpodautoscaler_spec_max_replicas{namespace="blog-system"}
```

#### Panel 3: CPU Utilization

```promql
sum(rate(container_cpu_usage_seconds_total{
  namespace="blog-system",
  pod=~"was.*",
  container="spring-boot"
}[5m])) by (pod)
/
sum(kube_pod_container_resource_requests{
  namespace="blog-system",
  pod=~"was.*",
  container="spring-boot",
  resource="cpu"
}) by (pod)
* 100
```

#### Panel 4: Network Receive Rate

```promql
sum(rate(container_network_receive_bytes_total{
  namespace="blog-system",
  pod=~"was.*",
  interface="eth0"
}[1m])) by (pod)
```

### 파일 위치

```
/home/jimin/k8s-manifests/monitoring/grafana-dashboard-configmap.yaml
/home/jimin/k8s-manifests/monitoring/grafana-dashboard-hpa.json
```

### 접속 방법

```
Grafana URL: http://grafana.jiminhome.shop
Dashboard: Blog System HPA Monitoring
```

---

## 실제 시나리오

### 시나리오 1: 트래픽 급증

**상황**: 블로그 글이 SNS에서 공유되어 트래픽 10배 증가

#### Before (단일 메트릭 HPA)

```
T+0s:   트래픽 급증 시작
T+30s:  네트워크 I/O 급증, CPU는 아직 정상
T+60s:  CPU 부하 증가 시작
T+90s:  CPU 70% 도달, HPA 감지
T+120s: Scale Up 시작 (stabilization 후)
T+150s: 새 Pod Ready

총 대응 시간: 2분 30초
사용자 영향: 지연 발생
```

#### After (Multi-Metric HPA)

```
T+0s:   트래픽 급증 시작
T+30s:  네트워크 100KB/s 초과, HPA 즉시 감지
T+90s:  Scale Up 시작 (60s stabilization)
T+120s: 새 Pod Ready

총 대응 시간: 2분
개선: 30초 단축 (20% 개선)
```

### 시나리오 2: 야간 트래픽 감소

**상황**: 새벽 2시, 트래픽 최저점

```
T+0:    트래픽 10% 수준
T+5min: CPU 20%, Network 10KB/s
        → 임계값 미달, Scale Down 대기 시작
T+10min: 5분 stabilization 완료
        → 50% Scale Down (4 → 2 replicas)

비용 절감: 50% 리소스 반환
```

---

## 트러블슈팅

### 문제 1: HPA가 스케일링하지 않음

**증상**: `kubectl get hpa`에서 TARGETS이 `<unknown>`

```bash
NAME      REFERENCE          TARGETS         MINPODS   MAXPODS
was-hpa   Rollout/was       <unknown>/70%   2         10
```

**원인**: Custom Metrics API 미작동

**해결**:
```bash
# 1. Prometheus Adapter 상태 확인
kubectl get pods -n monitoring | grep prometheus-adapter

# 2. Custom Metrics API 확인
kubectl get --raw /apis/custom.metrics.k8s.io/v1beta1 | jq .

# 3. 메트릭 존재 확인
kubectl get --raw "/apis/custom.metrics.k8s.io/v1beta1/namespaces/blog-system/pods/*/container_network_receive_bytes_per_second"

# 4. Prometheus Adapter 재시작
kubectl rollout restart deployment prometheus-adapter -n monitoring
```

### 문제 2: VPA 권장 값이 없음

**증상**: VPA status에 Recommendation이 비어있음

**원인**: 데이터 수집 기간 부족 (최소 24시간 필요)

**해결**:
```bash
# VPA 상태 확인
kubectl describe vpa was-vpa -n blog-system

# Recommender 로그 확인
kubectl logs -n kube-system -l app=vpa-recommender --tail=100
```

### 문제 3: HPA Ambiguous Selector

**증상**:
```
ScalingActive: False
Reason: AmbiguousSelector
```

**원인**: 동일 대상에 여러 HPA 존재

**해결**:
```bash
# 중복 HPA 확인
kubectl get hpa -n blog-system

# 불필요한 HPA 삭제
kubectl delete hpa <duplicate-hpa-name> -n blog-system
```

---

## 다음 단계

### ✅ 완료

- [x] Multi-Metric HPA 구성 (CPU + Network)
- [x] VPA Off 모드 설정
- [x] Grafana 대시보드 생성
- [x] ArgoCD 통합 (GitOps)

### ⏳ 선택 사항

- [ ] **Istio 메트릭 통합** (추후)
  - `istio_requests_total` 기반 HPA
  - 더 정확한 요청 수 기반 스케일링

- [ ] **PodDisruptionBudget 추가**
  ```yaml
  apiVersion: policy/v1
  kind: PodDisruptionBudget
  metadata:
    name: was-pdb
  spec:
    minAvailable: 1
    selector:
      matchLabels:
        app: was
  ```

- [ ] **알림 설정**
  - HPA Max Replicas 도달 시 Slack 알림
  - Scale Down 반복 시 알림

---

## 파일 목록

| 파일 | 경로 | 역할 |
|------|------|------|
| **HPA** | blog-system/hpa.yaml | WAS/WEB HPA 설정 |
| **VPA** | blog-system/vpa.yaml | WAS/WEB VPA 설정 |
| **Dashboard JSON** | monitoring/grafana-dashboard-hpa.json | 대시보드 정의 |
| **Dashboard ConfigMap** | monitoring/grafana-dashboard-configmap.yaml | Grafana 자동 로드 |
| **Prometheus Adapter** | monitoring/prometheus-adapter-values.yaml | Custom Metrics 규칙 |

---

**작성일**: 2026-01-22
**작성자**: Claude Opus 4.5
**문서 버전**: 1.0
**다음 단계**: Istio 메트릭 통합 (선택)
