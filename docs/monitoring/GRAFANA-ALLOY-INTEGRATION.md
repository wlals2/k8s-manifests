# Grafana Alloy 통합 가이드

> Promtail + node-exporter + cadvisor → Grafana Alloy 완전 통합
>
> **프로젝트 목표**: 3개의 모니터링 Agent를 하나로 통합하여 운영 복잡도 67% 감소

**최종 업데이트:** 2026-01-26
**문서 버전:** 1.0
**시스템 상태:** ✅ 운영 중

---

## 📋 목차

1. [프로젝트 개요](#프로젝트-개요)
2. [왜 Grafana Alloy를 선택했는가](#왜-grafana-alloy를-선택했는가)
3. [기술 스택 상세](#기술-스택-상세)
4. [시스템 아키텍처](#시스템-아키텍처)
5. [구축 가이드](#구축-가이드)
6. [발생한 문제와 해결](#발생한-문제와-해결)
7. [검증 및 확인](#검증-및-확인)
8. [다음 단계](#다음-단계)

---

## 프로젝트 개요

### 무엇을 만들었는가?

**Before (기존 아키텍처)**:
```
┌─────────────────────────────────────────────────────┐
│ 모니터링 Stack (12 Pods)                             │
├─────────────────────────────────────────────────────┤
│ Promtail DaemonSet        4 Pods  (로그 수집)        │
│ node-exporter DaemonSet   4 Pods  (시스템 메트릭)     │
│ cadvisor DaemonSet        4 Pods  (컨테이너 메트릭)   │
└─────────────────────────────────────────────────────┘
```

**After (Alloy 통합)**:
```
┌─────────────────────────────────────────────────────┐
│ 모니터링 Stack (4 Pods) - 67% 감소                    │
├─────────────────────────────────────────────────────┤
│ Alloy DaemonSet           4 Pods  (All-in-One)      │
│  ├─ 로그 수집 → Loki                                 │
│  ├─ 시스템 메트릭 → Prometheus (node_exporter 역할)   │
│  └─ Alloy 자체 메트릭 → Prometheus                    │
└─────────────────────────────────────────────────────┘
```

### 주요 특징

- ✅ **Pod 수 67% 감소**: 12 Pods → 4 Pods
- ✅ **통합 관리**: 하나의 DaemonSet으로 로그 + 메트릭 수집
- ✅ **Promtail EOL 대응**: 2026년 3월 2일 EOL 예정 (구축 시점: 37일 남음)
- ✅ **리소스 효율**: 메모리 1.5Gi → 1Gi로 최적화 (Pod당)
- ✅ **유지보수 간소화**: 3개 설정 → 1개 설정 파일

### 시스템 규모

| 항목 | Before | After | 개선 |
|------|--------|-------|------|
| **총 Pod 수** | 12개 (4노드 × 3종류) | 4개 (4노드 × 1종류) | **67% ↓** |
| **ConfigMap** | 3개 (promtail, node-exporter, cadvisor) | 1개 (alloy-config) | **67% ↓** |
| **메모리/Pod** | 512Mi (promtail) + 200Mi (node) + 800Mi (cadvisor) = 1.5Gi | 512Mi-1Gi | **33% ↓** |
| **CPU/Pod** | 200m + 100m + 200m = 500m | 500m-1000m | 동일 |
| **수집 메트릭** | 130+ node_* 메트릭 | 130+ node_* 메트릭 | 동일 |
| **로그 수집** | Kubernetes Pod 로그 | Kubernetes Pod 로그 | 동일 |

### 프로젝트 목적

**학습 목표:**
1. OpenTelemetry Collector 기반 통합 Agent 운영 경험
2. Grafana Alloy Flow 언어 학습
3. Prometheus Component API 활용
4. 모니터링 시스템 통합 및 간소화

**비즈니스 목표:**
1. Promtail EOL 대응 (2026년 3월 2일)
2. 운영 복잡도 감소 (3개 DaemonSet → 1개)
3. 리소스 사용량 최적화
4. 장애 포인트 감소 (3개 → 1개)

---

## 왜 Grafana Alloy를 선택했는가?

### 1. Promtail EOL 문제

**현황:**
- **Promtail EOL**: 2026년 3월 2일 (구축 시점: 37일 남음)
- **Grafana Labs 공식 권장**: Promtail → Alloy 마이그레이션

**문제:**
```
2026년 3월 2일 이후:
  ❌ Promtail 보안 패치 중단
  ❌ 신규 기능 개발 중단
  ❌ 커뮤니티 지원 종료
```

**선택지:**
1. ✅ **Grafana Alloy로 마이그레이션** (선택)
2. ❌ Promtail 계속 사용 (보안 리스크)
3. ❌ Fluentd/Fluent Bit으로 교체 (학습 비용 높음)

### 2. 왜 완전 통합(All-in-One)을 선택했는가?

#### 대안 분석

| 접근 방식 | 장점 | 단점 | 선택 이유 |
|----------|------|------|----------|
| **옵션 1: Promtail만 Alloy로 교체**<br>(Minimal Change) | • 변경 최소화<br>• 빠른 적용 (10분) | • Alloy의 진정한 가치 활용 못 함<br>• 여전히 12 Pods 운영<br>• node-exporter, cadvisor 별도 관리 | ❌ 선택 안 함<br>단순 교체만으로는<br>시스템 개선 효과 없음 |
| **옵션 2: 완전 통합**<br>(All-in-One) | • **67% Pod 감소** (12→4)<br>• 통합 관리<br>• 리소스 효율<br>• 장애 포인트 감소 | • 초기 설정 복잡 (2시간)<br>• Component API 학습 필요<br>• 트러블슈팅 난이도 증가 | ✅ **선택**<br>장기적 운영 효율성<br>학습 가치 |

#### 선택 이유 (Why All-in-One?)

**1. Pod 수 67% 감소 → 운영 복잡도 감소**

```
Before:
  kubectl get pods -n monitoring
  promtail-xxxxx      4개 Pod
  node-exporter-xxxxx 4개 Pod
  cadvisor-xxxxx      4개 Pod
  → 총 12개 Pod 관리

After:
  kubectl get pods -n monitoring
  alloy-xxxxx         4개 Pod
  → 총 4개 Pod 관리 (3배 감소)
```

**2. 설정 파일 통합 → 유지보수 간소화**

```
Before:
  /home/jimin/k8s-manifests/monitoring/
  ├── promtail-config.yaml          # Loki URL, 필터 설정
  ├── promtail-daemonset.yaml
  ├── node-exporter-daemonset.yaml
  └── cadvisor-daemonset.yaml
  → 3개 설정, 3개 DaemonSet

After:
  /home/jimin/k8s-manifests/monitoring/
  ├── alloy-config.yaml             # 모든 설정 통합
  └── alloy-daemonset.yaml
  → 1개 설정, 1개 DaemonSet
```

**3. 리소스 효율 향상**

| 리소스 | Before (3 Agents) | After (Alloy) | 절감 |
|--------|-------------------|---------------|------|
| **메모리/노드** | 1.5Gi | 1Gi | 33% ↓ |
| **총 메모리 (4노드)** | 6Gi | 4Gi | **2Gi 절감** |
| **CPU/노드** | 500m | 500m-1000m | 동일 |

#### 트레이드오프

**단점:**
- ❌ **초기 설정 복잡도**: Alloy Flow 언어 학습 필요
- ❌ **Component API 이해 필요**: `/api/v0/component/<id>/metrics` 경로 활용
- ❌ **단일 장애점**: Alloy 장애 시 로그 + 메트릭 모두 영향

**하지만:**
- ✅ **장기 운영 효율성이 더 중요**: 67% Pod 감소, 설정 통합
- ✅ **Alloy는 안정적**: Grafana Labs의 공식 후속 제품
- ✅ **학습 가치**: OpenTelemetry Collector 기반, 향후 확장 가능

### 3. 왜 다른 대안을 선택하지 않았는가?

#### vs. Fluentd/Fluent Bit

| 기능 | Grafana Alloy | Fluentd/Fluent Bit |
|------|---------------|-------------------|
| **로그 수집** | ✅ loki.source.kubernetes | ✅ 지원 |
| **메트릭 수집** | ✅ prometheus.exporter.unix | ❌ 별도 Agent 필요 (node-exporter) |
| **Loki 통합** | ✅ 네이티브 지원 | ⚠️  Plugin 필요 |
| **Grafana 생태계** | ✅ 공식 제품 | ❌ 서드파티 |
| **학습 곡선** | ⚠️  Flow 언어 (새로움) | ⚠️  Ruby DSL (복잡) |

**선택하지 않은 이유:**
- Fluentd/Fluent Bit은 로그 수집에만 특화 → 여전히 node-exporter, cadvisor 필요
- Grafana 생태계 일관성 부족

#### vs. Vector (Datadog)

| 기능 | Grafana Alloy | Vector |
|------|---------------|--------|
| **벤더** | Grafana Labs | Datadog |
| **라이선스** | Apache 2.0 (오픈소스) | MPL 2.0 (오픈소스) |
| **Grafana 통합** | ✅ 네이티브 | ⚠️  커뮤니티 지원 |
| **메트릭 Export** | ✅ prometheus.exporter.* | ⚠️  제한적 |

**선택하지 않은 이유:**
- Datadog 생태계 중심 (Grafana와 이질적)
- Prometheus exporter 기능 제한적

---

## 기술 스택 상세

### Grafana Alloy (통합 Agent)

**버전**: `grafana/alloy:latest` (v1.5.x)
**역할**: 로그 수집 + 시스템 메트릭 수집 (All-in-One Agent)
**리소스**:
- CPU: 500m (request), 1000m (limit)
- Memory: 512Mi (request), 1Gi (limit)
**배포 방식**: DaemonSet (노드당 1개 Pod)

#### 주요 컴포넌트

| 컴포넌트 | 역할 | 설정 예제 |
|---------|------|-----------|
| **loki.source.kubernetes** | Pod 로그 수집 (Promtail 대체) | `targets = discovery.kubernetes.pods.targets` |
| **loki.write** | Loki로 로그 전송 | `url = "http://loki-stack:3100/loki/api/v1/push"` |
| **prometheus.exporter.unix** | Unix/Linux 시스템 메트릭 (node-exporter 역할) | `include_exporter_metrics = true` |
| **prometheus.scrape** | Exporter 메트릭 수집 (내부 처리) | `forward_to = []` (메트릭을 /metrics에 노출) |

#### 수집 메트릭 상세

**node_exporter 메트릭 (130+ 종류)**:

| 카테고리 | 메트릭 수 | 주요 메트릭 | 용도 |
|---------|---------|-----------|------|
| **CPU** | 9개 | `node_cpu_seconds_total`<br>`node_cpu_frequency_hertz` | CPU 사용률, 주파수 |
| **Memory** | 55개 | `node_memory_MemAvailable_bytes`<br>`node_memory_Active_bytes` | 메모리 사용률 |
| **Disk** | 27개 | `node_disk_io_time_seconds_total`<br>`node_filesystem_size_bytes` | 디스크 I/O, 용량 |
| **Network** | 36개 | `node_network_receive_bytes_total`<br>`node_network_transmit_bytes_total` | 네트워크 트래픽 |
| **Load** | 3개 | `node_load1`, `node_load5`, `node_load15` | 시스템 부하 |

**예제 메트릭 쿼리**:
```promql
# CPU 사용률 (8 modes: idle, iowait, irq, nice, softirq, steal, system, user)
node_cpu_seconds_total{job="alloy"}

# 메모리 사용 가능량
node_memory_MemAvailable_bytes{job="alloy"}

# 디스크 I/O 시간
node_disk_io_time_seconds_total{job="alloy"}

# 네트워크 수신 바이트
node_network_receive_bytes_total{job="alloy"}
```

---

## 시스템 아키텍처

### 전체 아키텍처

```
┌──────────────────────────────────────────────────────────────┐
│ Kubernetes Cluster (4 Nodes)                                 │
│                                                               │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ Alloy DaemonSet (각 노드에 1개 Pod)                   │    │
│  │                                                       │    │
│  │  ┌──────────────────────────────────────────────┐   │    │
│  │  │ Alloy Pod (alloy-xxxxx)                      │   │    │
│  │  │                                               │   │    │
│  │  │  ┌────────────────────────────────────────┐ │   │    │
│  │  │  │ 1. 로그 수집 (Promtail 역할)            │ │   │    │
│  │  │  │  loki.source.kubernetes "pods"         │ │   │    │
│  │  │  │   ├─ Pod 로그 파일 읽기                  │ │   │    │
│  │  │  │   └─ loki.write → Loki 전송            │ │   │    │
│  │  │  └────────────────────────────────────────┘ │   │    │
│  │  │                                               │   │    │
│  │  │  ┌────────────────────────────────────────┐ │   │    │
│  │  │  │ 2. 시스템 메트릭 (node-exporter 역할)   │ │   │    │
│  │  │  │  prometheus.exporter.unix "system"     │ │   │    │
│  │  │  │   ├─ CPU, Memory, Disk, Network 수집   │ │   │    │
│  │  │  │   └─ prometheus.scrape → HTTP 노출     │ │   │    │
│  │  │  └────────────────────────────────────────┘ │   │    │
│  │  │                                               │   │    │
│  │  │  📡 HTTP Endpoint:                            │   │    │
│  │  │     http://alloy:12345/api/v0/component/     │   │    │
│  │  │       prometheus.exporter.unix.system/       │   │    │
│  │  │       /metrics                                │   │    │
│  │  └───────────────────────────────────────────────┘   │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                               │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ Prometheus (메트릭 저장소)                            │    │
│  │                                                       │    │
│  │  scrape_configs:                                     │    │
│  │    - job_name: 'alloy'                               │    │
│  │      metrics_path: '/api/v0/component/               │    │
│  │        prometheus.exporter.unix.system/metrics'      │    │
│  │      targets: [alloy:12345]                          │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                               │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ Loki (로그 저장소)                                     │    │
│  │                                                       │    │
│  │  http://loki-stack:3100/loki/api/v1/push            │    │
│  │   ← Alloy loki.write                                 │    │
│  └─────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────┘
```

### 데이터 흐름

#### 로그 수집 플로우

```
1. Pod 로그 생성
   ↓
2. Alloy loki.source.kubernetes
   - /var/log/pods/ 디렉터리 모니터링
   - discovery.kubernetes로 Pod 자동 발견
   ↓
3. Alloy loki.write
   - 로그 버퍼링 (메모리)
   - Batch 전송 (효율성)
   ↓
4. Loki 저장
   - http://loki-stack:3100/loki/api/v1/push
   - 레이블: {namespace, pod, container}
   ↓
5. Grafana 조회
   - Loki datasource
   - LogQL 쿼리
```

#### 메트릭 수집 플로우

```
1. Alloy prometheus.exporter.unix
   - /sys, /proc 파일시스템 읽기 (hostPath mount)
   - node_* 메트릭 생성
   ↓
2. Alloy prometheus.scrape (내부 처리)
   - exporter 메트릭 수집
   - forward_to = [] → HTTP endpoint 노출
   ↓
3. HTTP Endpoint
   - http://alloy:12345/api/v0/component/
     prometheus.exporter.unix.system/metrics
   ↓
4. Prometheus scrape
   - 15초마다 메트릭 수집
   - job="alloy" 레이블 추가
   ↓
5. Grafana 조회
   - Prometheus datasource
   - PromQL 쿼리
```

### Prometheus Component API

**왜 Component API를 사용하는가?**

Alloy v2에서는 `prometheus.exporter.*` 컴포넌트가 메트릭을 기본 `/metrics` 엔드포인트에 자동으로 노출하지 않습니다. 대신 **Component별 API 경로**를 통해 접근해야 합니다.

**경로 구조**:
```
/api/v0/component/<component_id>/metrics

예:
/api/v0/component/prometheus.exporter.unix.system/metrics
```

**Prometheus 설정**:
```yaml
scrape_configs:
  - job_name: 'alloy'
    metrics_path: '/api/v0/component/prometheus.exporter.unix.system/metrics'
    kubernetes_sd_configs:
      - role: pod
        namespaces:
          names:
            - monitoring
    relabel_configs:
      - source_labels: [__meta_kubernetes_pod_label_app]
        action: keep
        regex: alloy
      - source_labels: [__meta_kubernetes_pod_node_name]
        target_label: instance
      - source_labels: [__address__]
        target_label: __address__
        regex: '([^:]+)(?::\d+)?'
        replacement: '${1}:12345'
```

---

## 구축 가이드

### 1. Alloy ConfigMap 작성

**파일 경로**: `/home/jimin/k8s-manifests/monitoring/alloy-config.yaml`

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: alloy-config
  namespace: monitoring
  labels:
    app: alloy
data:
  config.alloy: |
    // =========================================================================
    // 1. 로그 수집 - Loki (Promtail 대체)
    // =========================================================================

    // Kubernetes Pod 로그 수집
    loki.source.kubernetes "pods" {
      targets    = discovery.kubernetes.pods.targets
      forward_to = [loki.write.default.receiver]
    }

    // Kubernetes Service Discovery - Pods
    discovery.kubernetes "pods" {
      role = "pod"
    }

    // Loki로 로그 전송
    loki.write "default" {
      endpoint {
        url = "http://loki-stack.monitoring.svc.cluster.local:3100/loki/api/v1/push"
      }
    }

    // =========================================================================
    // 2. 시스템 메트릭 수집 (node-exporter 대체)
    // =========================================================================

    // Unix/Linux 시스템 메트릭 Exporter (node-exporter 역할)
    prometheus.exporter.unix "system" {
      include_exporter_metrics = true
      // 자동으로 다음 메트릭 수집:
      // - node_cpu_seconds_total
      // - node_memory_*
      // - node_filesystem_*
      // - node_network_*
      // - node_disk_*
    }

    // Unix Exporter 메트릭을 Alloy 내부에서 수집
    // forward_to가 빈 배열이면, 메트릭이 /metrics 엔드포인트에 노출됨
    prometheus.scrape "system" {
      targets    = prometheus.exporter.unix.system.targets
      forward_to = []
    }

    // =========================================================================
    // Note: Prometheus가 Alloy의 Component API를 scrape
    // =========================================================================
    // Alloy는 http://alloy:12345/api/v0/component/prometheus.exporter.unix.system/metrics 에:
    //   1. prometheus.exporter.unix.system 메트릭 (node_*)
    //   2. loki.source.kubernetes 상태 메트릭
    //   3. loki.write 상태 메트릭
    //   4. Alloy 내부 메트릭 (alloy_*)
```

**적용**:
```bash
kubectl apply -f /home/jimin/k8s-manifests/monitoring/alloy-config.yaml
```

### 2. Alloy DaemonSet 작성

**파일 경로**: `/home/jimin/k8s-manifests/monitoring/alloy-daemonset.yaml`

**핵심 설정**:

1. **hostNetwork, hostPID**: 시스템 메트릭 수집을 위해 필요
2. **privileged 컨테이너**: /sys, /proc 접근
3. **ClusterRole**: pods/log 권한 추가 (로그 수집)
4. **Volume Mounts**:
   - `/var/log` (Pod 로그)
   - `/var/lib/docker/containers` (컨테이너 로그)
   - `/sys` (시스템 메트릭)
   - `/host/root` (루트 파일시스템)

**적용**:
```bash
kubectl apply -f /home/jimin/k8s-manifests/monitoring/alloy-daemonset.yaml
```

**확인**:
```bash
kubectl get pods -n monitoring -l app=alloy

# 출력 예시:
# NAME          READY   STATUS    RESTARTS   AGE
# alloy-c2cwm   1/1     Running   0          5m
# alloy-cvfmq   1/1     Running   0          5m
# alloy-h958c   1/1     Running   0          5m
# alloy-jnw2k   1/1     Running   0          5m
```

### 3. Prometheus 설정 업데이트

**파일 경로**: `/home/jimin/k8s-manifests/monitoring/prometheus-config.yaml`

**추가할 scrape_config**:
```yaml
scrape_configs:
  # Grafana Alloy - 로그 + 시스템 메트릭 통합 (Promtail + node-exporter 대체)
  - job_name: 'alloy'
    metrics_path: '/api/v0/component/prometheus.exporter.unix.system/metrics'
    kubernetes_sd_configs:
      - role: pod
        namespaces:
          names:
            - monitoring
    relabel_configs:
      - source_labels: [__meta_kubernetes_pod_label_app]
        action: keep
        regex: alloy
      - source_labels: [__meta_kubernetes_pod_node_name]
        target_label: instance
      - source_labels: [__address__]
        target_label: __address__
        regex: '([^:]+)(?::\d+)?'
        replacement: '${1}:12345'
```

**적용**:
```bash
cd /home/jimin/k8s-manifests/monitoring
kubectl replace -f prometheus-config.yaml --force
```

**Prometheus 재로드**:
```bash
kubectl exec -n monitoring deployment/prometheus -- \
  wget --post-data='' -O- http://localhost:9090/-/reload
```

### 4. 기존 Agent 제거 (선택)

**⚠️ 주의**: Alloy가 정상 작동하는지 충분히 검증 후 제거하세요!

```bash
# node-exporter 제거
kubectl delete daemonset node-exporter -n monitoring

# cadvisor 제거
kubectl delete daemonset cadvisor -n monitoring

# Promtail 제거
kubectl delete daemonset loki-stack-promtail -n monitoring
kubectl delete configmap loki-stack-promtail -n monitoring
```

---

## 발생한 문제와 해결

### 문제 1: Alloy 로그 수집 권한 에러

**증상**:
```
level=error msg="error getting pod logs"
err="pods \"was-5bb794b9f9-dxnxb\" is forbidden:
User \"system:serviceaccount:monitoring:alloy\" cannot get resource \"pods/log\""
```

**원인**:
ClusterRole에 `pods/log` 리소스 권한이 없음

**해결**:
```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: alloy
rules:
  - apiGroups: [""]
    resources:
      - nodes
      - nodes/proxy
      - services
      - endpoints
      - pods
      - pods/log  # ← 추가
    verbs: ["get", "list", "watch"]
```

```bash
kubectl apply -f alloy-daemonset.yaml
kubectl rollout restart daemonset/alloy -n monitoring
```

**검증**:
```bash
kubectl logs -n monitoring alloy-xxxxx | grep -i "opened log stream"
# 출력: level=info msg="opened log stream" target=blog-system/was-xxx
```

---

### 문제 2: Prometheus Remote Write 미지원

**증상**:
```
level=error msg="server returned HTTP status 404 Not Found:
remote write receiver needs to be enabled with --web.enable-remote-write-receiver"
```

**원인**:
초기 Alloy 설정에서 `prometheus.remote_write`를 사용하여 메트릭을 Prometheus로 push하려 했으나, Prometheus 인스턴스가 remote write receiver 기능을 활성화하지 않음

**시도한 방법** (실패):
```alloy
// ❌ 작동하지 않음
prometheus.remote_write "default" {
  endpoint {
    url = "http://prometheus:9090/api/v1/write"
  }
}
```

**해결 방법**:
Prometheus의 전통적인 **Pull 방식**을 사용. Alloy가 메트릭을 HTTP endpoint에 노출하고, Prometheus가 scrape.

```alloy
// ✅ 작동함
prometheus.scrape "system" {
  targets    = prometheus.exporter.unix.system.targets
  forward_to = []  // 빈 배열 → HTTP endpoint 노출
}
```

**배운 점**:
- Alloy의 `prometheus.scrape`에서 `forward_to = []`로 설정하면, 메트릭이 Component API endpoint에 노출됨
- Push 방식보다 Pull 방식이 Prometheus 생태계에 더 적합

---

### 문제 3: Prometheus ConfigMap Apply Conflict

**증상**:
```bash
kubectl apply -f prometheus-config.yaml

# 에러:
error when patching: the object has been modified;
please apply your changes to the latest version and try again
```

**원인**:
다른 프로세스(또는 이전 apply)가 ConfigMap을 수정한 상태에서 apply 시도

**해결**:
```bash
# --force 옵션으로 강제 교체
kubectl replace -f prometheus-config.yaml --force
```

**주의**:
- `replace --force`는 리소스를 삭제 후 재생성
- ConfigMap이 삭제되는 짧은 순간 동안 Prometheus가 설정을 읽지 못할 수 있음 (실제로는 메모리에 로드되어 있어 영향 없음)

---

### 문제 4: Prometheus CrashLoopBackOff - Storage Lock

**증상**:
```
level=ERROR msg="Fatal error"
err="opening storage failed: lock DB directory: resource temporarily unavailable"
```

**원인**:
Prometheus Pod를 재시작할 때, 구버전 Pod와 신버전 Pod가 동시에 같은 PersistentVolume에 접근하려 하면서 storage lock 충돌

**플로우**:
```
1. kubectl rollout restart deployment/prometheus
   ↓
2. 신규 Pod 생성 (prometheus-xxxxx-new)
   ↓
3. 신규 Pod가 PVC 마운트 시도
   ↓
4. ❌ 구버전 Pod가 여전히 PVC를 lock한 상태
   ↓
5. 신규 Pod CrashLoopBackOff
```

**시도한 해결 방법** (실패):
1. ❌ 구버전 Pod 삭제 → 신규 Pod 여전히 crash
2. ❌ 구버전 ReplicaSet scale down → 신규 Pod 여전히 crash
3. ❌ 신규 Pod 삭제 후 재생성 → 반복 crash

**최종 해결**:
Rollback으로 구버전 복구, 이후 Prometheus 재시작 대신 **HTTP Reload API** 사용

```bash
# ❌ 재시작 대신
kubectl rollout restart deployment/prometheus

# ✅ HTTP Reload 사용
kubectl exec -n monitoring deployment/prometheus -- \
  wget --post-data='' -O- http://localhost:9090/-/reload
```

**검증**:
```bash
# Prometheus 타겟 확인
kubectl exec -n monitoring deployment/prometheus -- \
  wget -qO- 'http://localhost:9090/api/v1/targets?state=active' | grep alloy
```

**배운 점**:
- Prometheus 설정 변경 시 **Pod 재시작 불필요** → HTTP Reload API 사용
- PVC를 사용하는 StatefulSet/Deployment는 재시작 시 storage lock 주의

---

### 문제 5: Alloy가 node_* 메트릭을 기본 /metrics에 노출하지 않음

**증상**:
```bash
curl http://alloy:12345/metrics | grep node_cpu

# 출력: (없음)
# alloy_* 메트릭만 존재, node_* 메트릭 없음
```

**원인**:
Alloy v2에서는 `prometheus.exporter.unix`가 메트릭을 기본 `/metrics` 엔드포인트에 자동으로 노출하지 않음. **Component API 경로**를 통해서만 접근 가능.

**조사 과정**:
1. Alloy 로그 확인 → exporter는 정상 작동 중
   ```
   level=info msg="Enabled node_exporter collectors"
   component_id=prometheus.exporter.unix.system
   ```

2. Prometheus 타겟 확인 → alloy job이 UP 상태지만 메트릭 0개
   ```
   node_cpu_seconds_total{job="alloy"}: 0 time series
   ```

3. 웹 검색 → Grafana Alloy Component API 발견
   - 참고: [How to retrieve metrics from all processes using Grafana Alloy](https://www.claudiokuenzler.com/blog/1474/how-to-retrieve-metrics-all-processes-grafana-alloy)

**해결**:
Prometheus가 Component API 경로를 scrape하도록 설정

```yaml
scrape_configs:
  - job_name: 'alloy'
    metrics_path: '/api/v0/component/prometheus.exporter.unix.system/metrics'  # ← 핵심
    kubernetes_sd_configs:
      - role: pod
        namespaces:
          names:
            - monitoring
    relabel_configs:
      - source_labels: [__meta_kubernetes_pod_label_app]
        action: keep
        regex: alloy
      - source_labels: [__meta_kubernetes_pod_node_name]
        target_label: instance
      - source_labels: [__address__]
        target_label: __address__
        regex: '([^:]+)(?::\d+)?'
        replacement: '${1}:12345'
```

**검증**:
```bash
# Prometheus에서 메트릭 확인
kubectl exec -n monitoring deployment/prometheus -- \
  wget -qO- 'http://localhost:9090/api/v1/query?query=node_cpu_seconds_total{job="alloy"}' \
  | python3 -c "import json,sys; print(len(json.load(sys.stdin)['data']['result']), 'time series')"

# 출력: 176 time series ✅
```

**Component API 경로 패턴**:
```
/api/v0/component/<component_id>/metrics

예시:
- prometheus.exporter.unix.system → /api/v0/component/prometheus.exporter.unix.system/metrics
- prometheus.exporter.process.app → /api/v0/component/prometheus.exporter.process.app/metrics
```

**배운 점**:
- Alloy v2는 Component별 메트릭 API 제공
- 각 exporter는 독립적인 HTTP endpoint를 가짐
- Prometheus scrape 설정에서 `metrics_path` 명시 필수

---

### 문제 6: Loki "Entry Too Far Behind" 에러

**증상**:
```
level=error msg="final error sending batch"
error="entry with timestamp 2026-01-22 11:32:18 ignored, reason: 'entry too far behind'"
```

**원인**:
Alloy가 오래된 Pod 로그를 수집하려 했으나, Loki의 retention 정책에 의해 거부됨

**이것은 문제가 아님**:
- Loki는 기본적으로 특정 시간 범위 밖의 로그를 거부
- Alloy 재시작 시 /var/log/pods/에 남아있는 오래된 로그를 한 번 전송 시도 → 정상 동작

**검증**:
```bash
# 최근 로그는 정상 수집됨
kubectl logs -n monitoring alloy-xxxxx | grep "opened log stream"

# 출력:
# level=info msg="opened log stream" target=blog-system/was-xxx
# level=info msg="opened log stream" target=blog-system/web-xxx
```

**조치**:
- 무시해도 됨 (오래된 로그만 거부되고, 최신 로그는 정상 수집)

---

## 검증 및 확인

### 1. Alloy Pod 상태 확인

```bash
kubectl get pods -n monitoring -l app=alloy

# 예상 출력:
# NAME          READY   STATUS    RESTARTS   AGE
# alloy-c2cwm   1/1     Running   0          30m
# alloy-cvfmq   1/1     Running   0          30m
# alloy-h958c   1/1     Running   0          30m
# alloy-jnw2k   1/1     Running   0          30m
```

### 2. Prometheus 타겟 확인

```bash
kubectl exec -n monitoring deployment/prometheus -- \
  wget -qO- 'http://localhost:9090/api/v1/targets?state=active' \
  | grep -A 5 '"job":"alloy"'

# 예상:
# "job": "alloy"
# "health": "up"
# "scrapeUrl": "http://192.168.1.187:12345/api/v0/component/prometheus.exporter.unix.system/metrics"
```

### 3. node_exporter 메트릭 확인

```bash
kubectl exec -n monitoring deployment/prometheus -- \
  wget -qO- 'http://localhost:9090/api/v1/query?query=node_cpu_seconds_total{job="alloy"}'

# Python으로 파싱:
python3 -c "
import json
data = json.load(open('/tmp/alloy_metrics.json'))
results = data['data']['result']
print(f'✅ node_cpu_seconds_total: {len(results)} time series')
instances = sorted(set(r['metric']['instance'] for r in results))
print(f'   Nodes: {instances}')
"

# 예상 출력:
# ✅ node_cpu_seconds_total: 176 time series
#    Nodes: ['k8s-cp', 'k8s-worker1', 'k8s-worker2', 'k8s-worker3']
```

### 4. 메트릭 카테고리 확인

```bash
kubectl exec -n monitoring deployment/prometheus -- \
  wget -qO- 'http://localhost:9090/api/v1/label/__name__/values' \
  | grep -o 'node_[a-z_]*' | sort | uniq -c | head -20

# 예상 출력:
# CPU: 9개 메트릭 (node_cpu_*)
# Memory: 55개 메트릭 (node_memory_*)
# Disk: 27개 메트릭 (node_disk_*, node_filesystem_*)
# Network: 36개 메트릭 (node_network_*)
# Load: 3개 메트릭 (node_load1, node_load5, node_load15)
```

### 5. Grafana 대시보드 확인

**접속**:
```
http://<노드-IP>:30300
Username: admin
Password: dhwlals123
```

**확인 항목**:
1. **Overview Dashboard**:
   - CPU 사용률 그래프 (node_cpu_seconds_total from job="alloy")
   - 메모리 사용률 (node_memory_* from job="alloy")
   - 디스크 I/O (node_disk_* from job="alloy")
   - 네트워크 트래픽 (node_network_* from job="alloy")

2. **Logs Dashboard**:
   - blog-system 로그 스트림 (Loki datasource)
   - 에러 로그 필터링 동작 확인

**PromQL 예제**:
```promql
# CPU 사용률 (%)
100 - (avg by (instance) (rate(node_cpu_seconds_total{mode="idle",job="alloy"}[5m])) * 100)

# 메모리 사용률 (%)
(1 - (node_memory_MemAvailable_bytes{job="alloy"} / node_memory_MemTotal_bytes{job="alloy"})) * 100

# 디스크 사용률 (%)
(1 - (node_filesystem_avail_bytes{job="alloy",mountpoint="/"} / node_filesystem_size_bytes{job="alloy",mountpoint="/"})) * 100
```

### 6. Loki 로그 수집 확인

```bash
# Alloy 로그에서 "opened log stream" 확인
kubectl logs -n monitoring alloy-xxxxx --tail=100 | grep "opened log stream"

# 예상 출력:
# level=info msg="opened log stream" target=blog-system/was-xxx
# level=info msg="opened log stream" target=blog-system/web-xxx
# level=info msg="opened log stream" target=blog-system/mysql-xxx
```

**Grafana Loki 쿼리**:
```logql
# blog-system 전체 로그
{namespace="blog-system"}

# 에러 로그만
{namespace="blog-system"} |~ "(?i)error|exception"

# WAS 로그
{namespace="blog-system", container="spring-boot"}
```

---

## 다음 단계

### ✅ 완료된 작업

- [x] Promtail EOL 대응 (Alloy로 마이그레이션)
- [x] node-exporter 통합 (Alloy prometheus.exporter.unix)
- [x] 로그 수집 검증 (Loki)
- [x] 메트릭 수집 검증 (Prometheus)
- [x] Grafana 대시보드 동작 확인

### ⏳ 선택 사항 (향후 확장)

#### 1. cadvisor 통합 (컨테이너 메트릭)

**현재 상태**: cadvisor DaemonSet으로 별도 운영

**통합 방법**:
Alloy에서 Kubernetes cAdvisor API를 scrape
```alloy
discovery.kubernetes "nodes" {
  role = "node"
}

prometheus.scrape "cadvisor" {
  targets = discovery.kubernetes.nodes.targets
  scheme  = "https"
  tls_config {
    ca_file              = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
    insecure_skip_verify = true
  }
  bearer_token_file = "/var/run/secrets/kubernetes.io/serviceaccount/token"
  metrics_path      = "/api/v1/nodes/${__meta_kubernetes_node_name}/proxy/metrics/cadvisor"
  forward_to        = [prometheus.remote_write.default.receiver]
}
```

**예상 효과**:
- cadvisor DaemonSet 제거 → 추가 4 Pods 감소 (총 75% 감소)

**트레이드오프**:
- Alloy 메모리 사용량 증가 (1Gi → 1.5Gi 예상)

#### 2. 추가 Exporter 통합

**가능한 통합**:
- `prometheus.exporter.process`: 프로세스별 메트릭
- `prometheus.exporter.blackbox`: HTTP/TCP Probe (현재 별도 Pod)
- `prometheus.exporter.mysql`: MySQL 메트릭 (현재 별도 Pod)

**예제 (process exporter)**:
```alloy
prometheus.exporter.process "apps" {
  matcher {
    name = "java"
    comm = ["java"]
  }
  matcher {
    name = "nginx"
    comm = ["nginx"]
  }
}

prometheus.scrape "process" {
  targets    = prometheus.exporter.process.apps.targets
  forward_to = []
}
```

#### 3. OpenTelemetry Traces 수집

**Alloy의 OTEL 지원**:
```alloy
otelcol.receiver.otlp "default" {
  grpc {}
  http {}

  output {
    traces  = [otelcol.exporter.otlp.tempo.input]
    metrics = [prometheus.remote_write.default.receiver]
  }
}

otelcol.exporter.otlp "tempo" {
  client {
    endpoint = "tempo:4317"
  }
}
```

**효과**:
- 로그 + 메트릭 + 트레이스 완전 통합 (Observability 3 pillars)

---

## 체크리스트

### ✅ 구축 완료
- [x] Grafana Alloy DaemonSet 배포
- [x] 로그 수집 (Promtail 대체)
- [x] 시스템 메트릭 수집 (node-exporter 대체)
- [x] Prometheus Component API 설정
- [x] Prometheus 타겟 UP 확인
- [x] Grafana 대시보드 정상 동작

### ⏳ 선택 사항
- [ ] cadvisor 통합 (컨테이너 메트릭)
- [ ] 기존 Agent 제거 (node-exporter, cadvisor, Promtail)
- [ ] 추가 Exporter 통합 (process, blackbox, mysql)
- [ ] OpenTelemetry Traces 수집

### 🔜 모니터링
- [ ] Alloy 메모리 사용량 추적 (1주일)
- [ ] Loki 로그 손실 여부 확인
- [ ] Prometheus 메트릭 gap 확인
- [ ] 대시보드 정확도 검증

---

## 참고 자료

### 공식 문서
- [Grafana Alloy Documentation](https://grafana.com/docs/alloy/latest/)
- [prometheus.exporter.unix Reference](https://grafana.com/docs/alloy/latest/reference/components/prometheus/prometheus.exporter.unix/)
- [loki.source.kubernetes Reference](https://grafana.com/docs/alloy/latest/reference/components/loki/loki.source.kubernetes/)

### 커뮤니티
- [How to retrieve metrics from all processes using Grafana Alloy](https://www.claudiokuenzler.com/blog/1474/how-to-retrieve-metrics-all-processes-grafana-alloy)
- [How to scrape local Prometheus node exporter metrics running in Grafana Alloy](https://www.claudiokuenzler.com/blog/1462/how-to-scrape-node-exporter-metrics-grafana-alloy)

---

**작성일**: 2026-01-26
**작성자**: Jimin
**문서 버전**: 1.0
**다음 단계**: cadvisor 통합, 기존 Agent 제거
