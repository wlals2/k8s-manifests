# Cilium 실무 활용 가이드 (금융권/엔터프라이즈)

> **작성일**: 2026-01-12
> **대상**: 처음부터 K8s 클러스터를 구축하는 금융권/엔터프라이즈
> **주제**: EKS 대신 자체 K8s 구축 시 Cilium CNI 활용 전략

---

## 🎯 왜 금융권은 Cilium을 선택하는가?

### 금융권의 핵심 요구사항

| 요구사항 | 기존 CNI | Cilium | 차이점 |
|---------|---------|--------|--------|
| **강력한 보안** | L3/L4만 | **L7까지** | API 엔드포인트별 접근 제어 |
| **규제 준수** | 제한적 | **완벽한 가시성** | 모든 네트워크 플로우 추적 |
| **Zero Trust** | 수동 구현 | **Built-in** | Identity 기반 정책 |
| **Multi-Cloud DR** | 복잡 | **ClusterMesh** | 클러스터 간 네이티브 통신 |
| **성능** | 보통 | **eBPF 고성능** | 30-40% 빠름 |
| **감사 로그** | 별도 구축 | **Hubble** | 실시간 네트워크 관측 |

---

## 🏦 금융권 실무 사례

### 사례 1: 국내 A 증권사

**배경**:
- 기존 IDC 환경에서 Kubernetes로 전환
- 온프레미스 K8s 클러스터 구축 (EKS 사용 안 함)
- 강력한 보안 정책 필요 (금융감독원 규제)

**Cilium 활용**:

#### 1. L7 네트워크 정책 (API 엔드포인트 보호)

```yaml
# 주식 거래 API 보호
apiVersion: cilium.io/v2
kind: CiliumNetworkPolicy
metadata:
  name: trading-api-policy
  namespace: trading
spec:
  endpointSelector:
    matchLabels:
      app: trading-api
  ingress:
    # 웹 서버에서만 접근 허용
    - fromEndpoints:
        - matchLabels:
            app: web-server
      toPorts:
        - ports:
            - port: "8080"
              protocol: TCP
          rules:
            http:
              # 주문 조회만 허용 (GET)
              - method: GET
                path: "/api/orders/.*"
              # 주문 생성은 차단 (POST) - 별도 인증 필요
```

**효과**:
- ✅ REST API 엔드포인트별 접근 제어
- ✅ HTTP Method 기반 정책 (GET 허용, POST 차단 등)
- ✅ 금융감독원 감사 시 네트워크 정책 증빙 가능

---

#### 2. Identity-based Security (Zero Trust)

```yaml
# PCI-DSS 준수: 카드 정보 DB 접근 제어
apiVersion: cilium.io/v2
kind: CiliumNetworkPolicy
metadata:
  name: card-db-policy
  namespace: payment
spec:
  endpointSelector:
    matchLabels:
      app: card-db
  ingress:
    # 결제 서비스에서만 접근 허용 (IP 아닌 Identity 기반)
    - fromEndpoints:
        - matchLabels:
            app: payment-service
            tier: backend
      toPorts:
        - ports:
            - port: "5432"
              protocol: TCP
```

**왜 Identity 기반인가?**

**기존 방식 (IP 기반)**:
```yaml
# ❌ 나쁜 예: IP 기반 정책
ingress:
  - from:
      - podSelector:
          matchLabels:
            app: payment-service
      - ipBlock:
          cidr: 10.0.1.0/24  # IP가 바뀌면 정책이 깨짐!
```

**Cilium (Identity 기반)**:
```yaml
# ✅ 좋은 예: Identity 기반 정책
ingress:
  - fromEndpoints:
      - matchLabels:
          app: payment-service
          # Pod IP가 바뀌어도 Identity는 유지됨
```

**효과**:
- ✅ Pod IP 변경 시에도 정책 유지
- ✅ HPA 스케일 아웃 시에도 자동 적용
- ✅ Zero Trust 아키텍처 구현

---

#### 3. Hubble로 규제 준수 (Compliance)

**금융감독원 요구사항**:
- 모든 네트워크 트래픽 기록 및 감사

**Hubble 활용**:
```bash
# 특정 서비스의 모든 네트워크 플로우 조회
hubble observe --namespace trading \
  --from-pod trading-api \
  --since 2026-01-01T00:00:00Z

# 거부된 트래픽만 조회 (보안 이벤트)
hubble observe --verdict DROPPED
```

**Hubble 출력 예시**:
```
Jan 12 10:30:45: trading-api:8080 <- web-server:35678 (ALLOWED, GET /api/orders/123)
Jan 12 10:30:50: trading-api:8080 <- unknown-pod:45678 (DROPPED, L7 policy denied)
Jan 12 10:30:55: card-db:5432 <- payment-service:52341 (ALLOWED, SQL query)
```

**효과**:
- ✅ 모든 네트워크 트래픽 추적 (Who, What, When, Where)
- ✅ 감사 로그 자동 생성
- ✅ 보안 이벤트 실시간 감지

---

### 사례 2: 글로벌 B 은행 (Multi-Cloud DR)

**배경**:
- AWS 서울 리전 (Primary)
- Azure 부산 리전 (DR)
- RTO 30분, RPO 5분 (엄격한 DR 요구사항)

**Cilium ClusterMesh 활용**:

```
┌─────────────────────────────────────────────────┐
│              ClusterMesh Architecture           │
├─────────────────────────────────────────────────┤
│                                                 │
│  AWS 서울 리전 (Primary)                         │
│  ┌─────────────────────────────┐               │
│  │  K8s Cluster A              │               │
│  │  ├─ Pod: 10.1.0.0/16        │               │
│  │  └─ Cilium ClusterMesh      │               │
│  └──────────────┬──────────────┘               │
│                 │                               │
│                 │ ClusterMesh VPN (IPsec)       │
│                 │                               │
│  ┌──────────────▼──────────────┐               │
│  │  K8s Cluster B              │               │
│  │  ├─ Pod: 10.2.0.0/16        │               │
│  │  └─ Cilium ClusterMesh      │               │
│  └─────────────────────────────┘               │
│  Azure 부산 리전 (DR)                            │
│                                                 │
└─────────────────────────────────────────────────┘
```

**ClusterMesh 설정**:
```bash
# Cluster A (AWS)에서 ClusterMesh 활성화
cilium clustermesh enable --context aws-seoul

# Cluster B (Azure)에서 ClusterMesh 활성화
cilium clustermesh enable --context azure-busan

# 클러스터 간 연결
cilium clustermesh connect --context aws-seoul --destination-context azure-busan
```

**Global Service (Multi-Cluster Load Balancing)**:
```yaml
# AWS와 Azure 간 자동 Failover
apiVersion: v1
kind: Service
metadata:
  name: payment-service
  namespace: payment
  annotations:
    io.cilium/global-service: "true"  # Global Service 활성화
spec:
  type: ClusterIP
  ports:
    - port: 8080
      targetPort: 8080
  selector:
    app: payment-service
```

**동작 방식**:
1. **정상 시**: AWS 클러스터로 트래픽 전송
2. **AWS 장애 시**: 자동으로 Azure 클러스터로 Failover
3. **RTO**: ~30초 (Cilium이 자동 감지 및 재라우팅)

**효과**:
- ✅ 클러스터 간 네이티브 통신 (VPN 터널 자동 설정)
- ✅ Global Service로 Multi-Cloud Load Balancing
- ✅ RTO 30초 달성 (기존 Route53 Failover 2분 → 30초)

---

### 사례 3: C 카드사 (PCI-DSS 준수)

**배경**:
- PCI-DSS (Payment Card Industry Data Security Standard) 준수 필요
- 카드 정보 처리 시스템의 네트워크 격리 필수

**Cilium Network Segmentation**:

```yaml
# Tier 1: DMZ (Public)
---
apiVersion: cilium.io/v2
kind: CiliumNetworkPolicy
metadata:
  name: dmz-policy
  namespace: dmz
spec:
  endpointSelector:
    matchLabels:
      tier: dmz
  ingress:
    # 인터넷에서 HTTPS만 허용
    - fromCIDR:
        - 0.0.0.0/0
      toPorts:
        - ports:
            - port: "443"
              protocol: TCP
  egress:
    # Tier 2 (Application)로만 통신 허용
    - toEndpoints:
        - matchLabels:
            tier: application

---
# Tier 2: Application
apiVersion: cilium.io/v2
kind: CiliumNetworkPolicy
metadata:
  name: app-policy
  namespace: application
spec:
  endpointSelector:
    matchLabels:
      tier: application
  ingress:
    # Tier 1 (DMZ)에서만 접근 허용
    - fromEndpoints:
        - matchLabels:
            tier: dmz
  egress:
    # Tier 3 (Database)로만 통신 허용
    - toEndpoints:
        - matchLabels:
            tier: database

---
# Tier 3: Database (카드 정보 저장)
apiVersion: cilium.io/v2
kind: CiliumNetworkPolicy
metadata:
  name: db-policy
  namespace: database
spec:
  endpointSelector:
    matchLabels:
      tier: database
  ingress:
    # Tier 2 (Application)에서만 접근 허용
    - fromEndpoints:
        - matchLabels:
            tier: application
  egress:
    # 외부 통신 완전 차단 (Database는 외부로 나가면 안 됨)
    - toEndpoints:
        - matchLabels:
            tier: application
```

**3-Tier 네트워크 격리**:
```
Internet
   │
   ▼
┌──────────┐
│  DMZ     │ (HTTPS only)
│ (Tier 1) │
└────┬─────┘
     │
     ▼
┌──────────┐
│   App    │ (Internal API)
│ (Tier 2) │
└────┬─────┘
     │
     ▼
┌──────────┐
│    DB    │ (Encrypted, No Egress)
│ (Tier 3) │
└──────────┘
```

**효과**:
- ✅ PCI-DSS Requirement 1.3 (Network Segmentation) 준수
- ✅ 카드 정보 DB는 외부 통신 완전 차단
- ✅ 감사 시 네트워크 격리 증빙 가능

---

## 🆚 EKS vs 자체 K8s 구축 (Cilium 관점)

### AWS EKS

**기본 CNI**: AWS VPC CNI
- ✅ AWS 네이티브 통합 (보안 그룹, VPC 라우팅)
- ❌ eBPF 미사용 (성능 낮음)
- ❌ L7 정책 불가
- ❌ Hubble 없음

**Cilium 사용 가능** (EKS 1.21+):
```bash
# EKS에서 Cilium 설치
helm install cilium cilium/cilium --version 1.18.4 \
  --namespace kube-system \
  --set eni.enabled=true \
  --set ipam.mode=eni \
  --set egressMasqueradeInterfaces=eth0 \
  --set routingMode=native
```

**EKS + Cilium 장점**:
- ✅ AWS VPC ENI IPAM 사용 (IP 부족 문제 해결)
- ✅ eBPF 성능 향상
- ✅ L7 정책 + Hubble

**EKS 한계**:
- ❌ EKS 자체가 비쌈 ($0.10/hour = $73/월)
- ❌ Control Plane 커스터마이징 불가
- ❌ On-Premise DR 불가 (AWS 종속)

---

### 자체 K8s 구축 + Cilium

**장점**:

| 항목 | EKS | 자체 K8s + Cilium |
|------|-----|-------------------|
| **비용** | $73/월 (클러스터당) + 노드 | **노드 비용만** |
| **Control Plane** | AWS 관리 (커스터마이징 불가) | **완전한 제어** |
| **CNI 선택** | AWS VPC CNI (기본) | **Cilium 최적화 가능** |
| **Multi-Cloud** | 어려움 | **ClusterMesh로 쉬움** |
| **On-Premise** | 불가 | **가능** |
| **eBPF 최적화** | 제한적 | **완전한 최적화** |
| **Hubble** | 설치 필요 | **네이티브 통합** |

**비용 비교 (3년 TCO)**:

```
EKS (3 클러스터):
- EKS 비용: $73/월 × 3 = $219/월 × 36개월 = $7,884
- Worker 노드: $300/월 × 36개월 = $10,800
- 총합: $18,684

자체 K8s (3 클러스터):
- Control Plane (t3.medium × 3): $30/월 × 36개월 = $1,080
- Worker 노드: $300/월 × 36개월 = $10,800
- 총합: $11,880

절감: $6,804 (36%)
```

---

## 🏗️ 금융권을 위한 K8s + Cilium 구축 가이드

### Phase 1: 클러스터 설계

#### 1.1 아키텍처 결정

**Multi-Cluster 전략**:
```
┌─────────────────────────────────────────────┐
│        금융권 K8s 아키텍처 (예시)            │
├─────────────────────────────────────────────┤
│                                             │
│  Cluster 1: Production (서울 IDC)           │
│  ├─ CNI: Cilium                             │
│  ├─ Routing: Native (BGP)                   │
│  └─ Hubble: Enabled                         │
│                                             │
│  Cluster 2: DR (부산 IDC)                    │
│  ├─ CNI: Cilium                             │
│  ├─ ClusterMesh: Connected to Cluster 1     │
│  └─ Global Service: Enabled                 │
│                                             │
│  Cluster 3: Dev/Staging (Cloud)             │
│  ├─ CNI: Cilium                             │
│  └─ Isolated (No ClusterMesh)               │
│                                             │
└─────────────────────────────────────────────┘
```

#### 1.2 네트워크 설계

| 요소 | 설정 | 이유 |
|------|------|------|
| **Routing Mode** | Native (BGP) | VXLAN 오버헤드 제거 |
| **IPAM** | Cluster-Pool | Cilium이 IP 관리 |
| **kube-proxy 대체** | Enabled | eBPF로 성능 향상 |
| **Hubble** | Enabled | 규제 준수 |
| **Encryption** | IPsec/WireGuard | 데이터 암호화 |

---

### Phase 2: Cilium 설치 (Production-Ready)

#### 2.1 Helm Values (금융권 최적화)

**values-production.yaml**:
```yaml
# Cilium Helm Values for Financial Services
cluster:
  name: prod-cluster-seoul
  id: 1

# eBPF 최적화
bpf:
  masquerade: true
  lbExternalClusterIP: false
  tproxy: true

# Native Routing (VXLAN 대신)
routingMode: native
autoDirectNodeRoutes: true
ipv4NativeRoutingCIDR: 10.0.0.0/8

# kube-proxy 대체
kubeProxyReplacement: "true"
k8sServiceHost: 192.168.1.187  # API Server IP
k8sServicePort: 6443

# Hubble (관측성)
hubble:
  enabled: true
  relay:
    enabled: true
    replicas: 2
  ui:
    enabled: true
    replicas: 2
  metrics:
    enabled:
      - dns:query
      - drop
      - tcp
      - flow
      - icmp
      - http

# 암호화 (IPsec)
encryption:
  enabled: true
  type: ipsec
  nodeEncryption: true

# BGP (On-Premise 환경)
bgp:
  enabled: true
  announce:
    loadbalancerIP: true
    podCIDR: true

# Policy Enforcement
policyEnforcementMode: always  # 모든 Pod에 정책 적용

# 감사 로그
monitor:
  enabled: true
```

#### 2.2 설치

```bash
# Cilium Helm Chart 추가
helm repo add cilium https://helm.cilium.io/
helm repo update

# Cilium 설치
helm install cilium cilium/cilium \
  --version 1.18.4 \
  --namespace kube-system \
  --values values-production.yaml

# 설치 확인
cilium status --wait
```

---

### Phase 3: 보안 정책 적용

#### 3.1 Default Deny 정책

```yaml
# 모든 네임스페이스에 적용: 명시적 허용만 통신 가능
apiVersion: cilium.io/v2
kind: CiliumNetworkPolicy
metadata:
  name: default-deny-all
  namespace: production
spec:
  endpointSelector: {}  # 모든 Pod에 적용
  ingress: []  # 모든 Ingress 차단
  egress: []   # 모든 Egress 차단
```

#### 3.2 금융 거래 서비스 정책

```yaml
# 주식 거래 API
apiVersion: cilium.io/v2
kind: CiliumNetworkPolicy
metadata:
  name: trading-api-policy
  namespace: trading
spec:
  endpointSelector:
    matchLabels:
      app: trading-api
      tier: backend
  ingress:
    # Web Server에서만 접근
    - fromEndpoints:
        - matchLabels:
            app: web-server
            tier: frontend
      toPorts:
        - ports:
            - port: "8080"
              protocol: TCP
          rules:
            http:
              # 조회 API만 허용
              - method: GET
                path: "/api/trades/.*"
              - method: GET
                path: "/api/orders/.*"
  egress:
    # Database로만 통신
    - toEndpoints:
        - matchLabels:
            app: trading-db
            tier: database
      toPorts:
        - ports:
            - port: "5432"
              protocol: TCP
    # DNS 허용
    - toEndpoints:
        - matchLabels:
            k8s:io.kubernetes.pod.namespace: kube-system
            k8s:k8s-app: kube-dns
      toPorts:
        - ports:
            - port: "53"
              protocol: UDP
```

---

### Phase 4: Hubble 감사 로그

#### 4.1 Hubble CLI 설치

```bash
# Hubble CLI 설치
HUBBLE_VERSION=v0.13.0
curl -L --remote-name-all https://github.com/cilium/hubble/releases/download/$HUBBLE_VERSION/hubble-linux-amd64.tar.gz
tar xzvf hubble-linux-amd64.tar.gz
sudo mv hubble /usr/local/bin/

# Hubble 연결
cilium hubble port-forward &
```

#### 4.2 감사 로그 조회

```bash
# 1. 모든 네트워크 플로우 실시간 모니터링
hubble observe

# 2. 특정 서비스의 트래픽만 조회
hubble observe --namespace trading --pod trading-api

# 3. 거부된 트래픽만 조회 (보안 이벤트)
hubble observe --verdict DROPPED

# 4. L7 HTTP 트래픽만 조회
hubble observe --protocol http

# 5. 특정 시간대 로그 내보내기 (감사용)
hubble observe --since 2026-01-01T00:00:00Z \
  --until 2026-01-31T23:59:59Z \
  --output json > audit-log-jan-2026.json
```

#### 4.3 Grafana 대시보드 연동

```yaml
# Prometheus로 Hubble 메트릭 수집
apiVersion: v1
kind: Service
metadata:
  name: hubble-metrics
  namespace: kube-system
spec:
  selector:
    k8s-app: cilium
  ports:
    - port: 9965
      name: hubble-metrics
```

**Grafana 대시보드**:
- 네트워크 플로우 시각화
- 거부된 트래픽 통계
- L7 HTTP 메트릭

---

## 🚀 금융권 Best Practices

### 1. 네트워크 정책 설계 원칙

**Principle of Least Privilege (최소 권한 원칙)**:
```yaml
# ❌ 나쁜 예: 너무 넓은 정책
ingress:
  - fromEndpoints:
      - {}  # 모든 Pod 허용

# ✅ 좋은 예: 최소 권한
ingress:
  - fromEndpoints:
      - matchLabels:
          app: frontend
          version: v2
          env: production
```

---

### 2. Multi-Cluster 전략

**DR 클러스터 구성**:
- Primary (서울) + DR (부산)
- ClusterMesh로 연결
- Global Service로 자동 Failover

**RTO 목표**:
- Route53 Failover: 2분
- Cilium ClusterMesh: 30초 ✅ (4배 빠름)

---

### 3. 규제 준수 체크리스트

- [ ] 모든 네트워크 트래픽 로깅 (Hubble)
- [ ] L7 정책 적용 (API 엔드포인트별 제어)
- [ ] Default Deny 정책 적용
- [ ] 암호화 활성화 (IPsec/WireGuard)
- [ ] 감사 로그 3년 보관
- [ ] 네트워크 격리 (PCI-DSS Tier 분리)

---

## 📊 ROI 분석

### 비용 절감

**EKS 대비**:
- 3년 절감: $6,804 (36%)

**운영 효율**:
- 트러블슈팅 시간: 50% 감소 (Hubble 덕분)
- 정책 관리 시간: 30% 감소 (L7 정책으로 세밀한 제어)

### 성능 향상

**eBPF vs iptables**:
- Latency: 30% 감소
- Throughput: 40% 증가

---

## 🔗 참고 자료

| 자료 | URL |
|------|-----|
| **Cilium 금융권 사례** | https://cilium.io/use-cases/financial-services/ |
| **PCI-DSS 준수 가이드** | https://docs.cilium.io/en/stable/security/policy/ |
| **ClusterMesh 설정** | https://docs.cilium.io/en/stable/gettingstarted/clustermesh/ |
| **Hubble 관측성** | https://docs.cilium.io/en/stable/gettingstarted/hubble/ |

---

**작성일**: 2026-01-12
**버전**: 1.0
