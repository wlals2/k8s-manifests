# Nginx Proxy를 통한 Istio Service Mesh 구현

> blog-system에서 web → was 트래픽을 Istio mesh로 통과시켜 mTLS 암호화 및 Kiali 시각화 달성

**프로젝트 목표**: API 트래픽을 nginx proxy를 통해 라우팅하여 Istio service mesh 가시성 확보

**최종 업데이트:** 2026-01-20
**문서 버전:** 1.0
**시스템 상태:** ✅ 완료

---

## 📋 목차

1. [프로젝트 개요](#1-프로젝트-개요)
2. [왜 이 구조가 필요했는가](#2-왜-이-구조가-필요했는가)
3. [아키텍처 변경 사항](#3-아키텍처-변경-사항)
4. [구현 과정 및 문제 해결](#4-구현-과정-및-문제-해결)
5. [최종 검증](#5-최종-검증)
6. [트러블슈팅 가이드](#6-트러블슈팅-가이드)
7. [다음 단계 (고도화 옵션)](#7-다음-단계-고도화-옵션)

---

## 1. 프로젝트 개요

### Before (개선 전)

```
[Nginx Ingress] → /api → [was-service:8080] (Istio mesh 우회)
                                ↓
                          [was pod]
```

**문제점:**
- ❌ Ingress가 `/api`를 was-service:8080으로 직접 라우팅
- ❌ nginx proxy 미사용 → Istio mesh 우회
- ❌ Kiali에서 web → was 연결 안 보임
- ❌ mTLS 미적용
- ❌ Istio 트래픽 정책 (Retry, Timeout, Circuit Breaking) 적용 불가

### After (개선 후)

```
[Nginx Ingress] → /api → [web-service:80] → [web nginx proxy]
                                                    ↓ (Istio mesh 통과)
                                              [was-service:8080]
                                                    ↓
                                              [was pod]
```

**개선 효과:**
- ✅ 모든 API 트래픽이 Istio mesh 통과
- ✅ mTLS 암호화 적용 (web ↔ was)
- ✅ Kiali Workload graph에서 전체 플로우 시각화
- ✅ Istio 트래픽 정책 적용 가능 (DestinationRule, VirtualService)
- ✅ istio-proxy 로그에서 요청 추적 가능

### 시스템 규모

| 항목 | 수치 |
|------|------|
| **Namespace** | blog-system |
| **Services** | web-service, was-service, mysql |
| **Mesh Coverage** | 66% (web, was 포함 / mysql 제외) |
| **mTLS Status** | PERMISSIVE mode (Nginx Ingress 호환) |
| **DestinationRules** | 2개 (web, was) |
| **VirtualServices** | 1개 (web - Argo Rollouts 연동) |

---

## 2. 왜 이 구조가 필요했는가?

### 문제 1: Istio mesh 우회

**Before:**
```
External → Nginx Ingress → /api → was-service:8080 (mesh 우회)
```

**문제점:**
- Istio가 트래픽을 추적하지 못함
- Kiali에서 연결이 보이지 않음
- mTLS 암호화 불가능
- DestinationRule의 Connection Pool, Circuit Breaking 정책 미적용
- 트래픽 미러링, Fault Injection 같은 고급 기능 사용 불가

**After:**
```
External → Nginx Ingress → /api → web-service:80 → web nginx → was-service:8080
                                                        ↑
                                                 Istio mesh 통과 ✅
```

**효과:**
- 모든 트래픽이 istio-proxy sidecar를 거침
- Kiali에서 실시간 트래픽 시각화
- mTLS 자동 적용
- Istio 트래픽 정책 활성화

---

### 문제 2: PassthroughCluster 오류

**증상:**
- Kiali에서 모든 트래픽이 "PassthroughCluster"로 표시
- web → was 연결이 검정색 (mesh 외부 트래픽)

**원인:**
```nginx
# nginx config (잘못된 설정)
location /api {
    proxy_pass http://was-service:8080;
    proxy_set_header Host $host;  # ← blog.jiminhome.shop 전달
}
```

Istio는 `Host: blog.jiminhome.shop` 헤더를 보고 **외부 트래픽**으로 판단:
```
Istio 판단 로직:
  Host == 클러스터 내부 서비스명 ? mesh 내부 : PassthroughCluster (외부)
```

**해결:**
```nginx
# nginx config (수정)
location /api {
    proxy_pass http://was-service.blog-system.svc.cluster.local:8080;
    proxy_set_header Host was-service;  # ← Istio가 내부 트래픽으로 인식
}
```

**결과:**
- Istio가 트래픽을 mesh 내부로 인식
- Kiali에서 녹색 연결선으로 표시
- mTLS 자동 적용

---

### 문제 3: DestinationRule 누락

**증상:**
- Host 헤더 수정 후에도 일부 PassthroughCluster 발생
- mTLS 아이콘이 Kiali에 표시되지 않음

**원인:**
- was-service에 DestinationRule 없음
- Istio가 트래픽 정책(mTLS, Connection Pool)을 적용할 설정 부재

**해결:**
```yaml
# was-destinationrule.yaml (신규 생성)
apiVersion: networking.istio.io/v1beta1
kind: DestinationRule
metadata:
  name: was-dest-rule
  namespace: blog-system
spec:
  host: was-service

  trafficPolicy:
    tls:
      mode: ISTIO_MUTUAL  # mTLS 명시적 강제

    connectionPool:
      http:
        http1MaxPendingRequests: 100
        http2MaxRequests: 100
        maxRequestsPerConnection: 10

    loadBalancer:
      simple: ROUND_ROBIN
```

**효과:**
- mTLS 명시적으로 활성화
- Connection Pool로 과부하 방지
- Load Balancing 정책 적용

---

### 문제 4: STRICT mTLS의 502 에러

**배경:**
```yaml
# 초기 설정 (실패)
apiVersion: security.istio.io/v1beta1
kind: PeerAuthentication
metadata:
  name: default
  namespace: blog-system
spec:
  mtls:
    mode: STRICT  # 모든 통신 mTLS 강제
```

**문제:**
```
Nginx Ingress Controller (mesh 외부)
        ↓ plain text (HTTP)
web-service:80 ← ❌ 502 Bad Gateway (mTLS 요구)
```

**원인:**
- Nginx Ingress Controller는 **Istio mesh 외부**에서 동작
- plain text로 web-service:80 접근 시도
- STRICT 모드: mTLS만 허용 → plain text 거부 → 502 에러

**해결:**
```yaml
# mtls-peerauthentication.yaml (수정)
spec:
  mtls:
    mode: PERMISSIVE  # mTLS + plain text 둘 다 허용
```

**결과:**
| 구간 | 프로토콜 | 이유 |
|------|----------|------|
| Nginx Ingress → web:80 | Plain text | PERMISSIVE 허용 |
| web → was:8080 | **mTLS** | Istio 자동 적용 (DestinationRule) |
| was → mysql:3306 | Plain text | JDBC 호환성 |

**Git History:**
```bash
commit 0b8d573 - "Fix: Change mTLS mode from STRICT to PERMISSIVE for Ingress access"
```

---

## 3. 아키텍처 변경 사항

### 전체 플로우 다이어그램

```
┌─────────────────────────────────────────────────────────────┐
│                    External Traffic                          │
│                  (Internet Users)                            │
└──────────────────┬──────────────────────────────────────────┘
                   │ HTTPS
                   ▼
        ┌──────────────────────┐
        │  Nginx Ingress       │
        │  Controller          │
        │  (plain text)        │
        └──────────┬───────────┘
                   │ /api → web-service:80
                   │ /board → web-service:80
                   │ / → web-service:80
                   ▼
        ┌──────────────────────┐
        │  web-service         │
        │  (ClusterIP)         │
        └──────────┬───────────┘
                   │
    ┌──────────────▼──────────────────┐
    │  web pod                         │
    │  ┌───────────────────────────┐  │
    │  │ nginx (reverse proxy)     │  │
    │  │ /health → 200 OK          │  │
    │  │ /api → was-service:8080   │  │
    │  │ / → static files          │  │
    │  └───────────┬───────────────┘  │
    │              │                   │
    │  ┌───────────▼───────────────┐  │
    │  │ istio-proxy (sidecar)     │  │
    │  │ - mTLS encryption         │  │
    │  │ - Connection Pool         │  │
    │  │ - Load Balancing          │  │
    │  └───────────┬───────────────┘  │
    └──────────────┼───────────────────┘
                   │ mTLS (encrypted) 🔒
    ┌──────────────▼───────────────────┐
    │  was pod                         │
    │  ┌───────────────────────────┐  │
    │  │ istio-proxy (sidecar)     │  │
    │  │ - mTLS decryption         │  │
    │  │ - Traffic monitoring      │  │
    │  └───────────┬───────────────┘  │
    │              │                   │
    │  ┌───────────▼───────────────┐  │
    │  │ Spring Boot (WAS)         │  │
    │  │ :8080                     │  │
    │  │ /actuator/health          │  │
    │  └───────────┬───────────────┘  │
    └──────────────┼───────────────────┘
                   │ plain text (JDBC)
                   ▼
        ┌──────────────────────┐
        │  mysql               │
        │  :3306               │
        │  (mesh 제외)         │
        └──────────────────────┘
```

### 수정된 파일 목록

| 파일 | 변경 내용 | Commit |
|------|----------|--------|
| **blog-ingress.yaml** | `/api` route: was-service:8080 → web-service:80 | 5ca0fb5 |
| **web-nginx-config.yaml** | FQDN 사용 + Host 헤더 수정 | 6818ad7 |
| **was-destinationrule.yaml** | 신규 생성 (mTLS, Connection Pool) | cec7fe2 |

---

### 상세 변경 내역

#### 1. blog-ingress.yaml

**Before:**
```yaml
- path: /api
  pathType: Prefix
  backend:
    service:
      name: was-service  # 직접 was로 라우팅
      port:
        number: 8080
```

**After:**
```yaml
- path: /api
  pathType: Prefix
  backend:
    service:
      name: web-service  # nginx proxy를 거침
      port:
        number: 80
```

**파일 위치:** `/home/jimin/k8s-manifests/blog-system/blog-ingress.yaml`

---

#### 2. web-nginx-config.yaml

**Before:**
```nginx
location /api {
    proxy_pass http://was-service:8080;  # 짧은 이름
    proxy_set_header Host $host;  # blog.jiminhome.shop (외부 도메인)
}
```

**After:**
```nginx
location /api {
    # FQDN 사용 (Istio mesh 인식)
    proxy_pass http://was-service.blog-system.svc.cluster.local:8080;

    # Istio가 내부 트래픽으로 인식하도록 Host 헤더 변경
    proxy_set_header Host was-service;

    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Connection "";

    # Timeout 설정
    proxy_connect_timeout 5s;
    proxy_send_timeout 5s;
    proxy_read_timeout 5s;
}
```

**왜 FQDN을 사용하는가?**
- Kubernetes DNS 명시적 해석
- Istio가 트래픽을 추적하기 쉬움
- Namespace 경계를 명확하게 함

**파일 위치:** `/home/jimin/k8s-manifests/blog-system/web-nginx-config.yaml`

---

#### 3. was-destinationrule.yaml (신규)

```yaml
# ==============================================================================
# WAS DestinationRule
# ==============================================================================
# 목적: WAS 트래픽에 대한 Istio 정책 설정
#
# 주요 기능:
# - mTLS 활성화: web → was 트래픽 암호화
# - Connection Pool 설정: 동시 연결 수 제한
# - Load Balancing: ROUND_ROBIN 방식
#
# 참고:
# - PeerAuthentication이 PERMISSIVE 모드이므로 mTLS는 선택적
# - ISTIO_MUTUAL: mTLS 사용 (Istio가 인증서 자동 관리)
# ==============================================================================
apiVersion: networking.istio.io/v1beta1
kind: DestinationRule
metadata:
  name: was-dest-rule
  namespace: blog-system
  labels:
    app: was
    tier: backend
spec:
  host: was-service  # Service 이름

  # 트래픽 정책
  trafficPolicy:
    # mTLS 설정
    tls:
      mode: ISTIO_MUTUAL  # mTLS 강제 (Istio가 인증서 자동 관리)

    # Connection Pool 설정
    connectionPool:
      http:
        http1MaxPendingRequests: 100  # 대기 가능한 최대 요청 수
        http2MaxRequests: 100          # HTTP/2 최대 요청 수
        maxRequestsPerConnection: 10   # 커넥션당 최대 요청 수

    # Load Balancing
    loadBalancer:
      simple: ROUND_ROBIN  # 라운드 로빈 방식
```

**주요 설정 설명:**

| 설정 | 값 | 이유 |
|------|----|----|
| **tls.mode** | ISTIO_MUTUAL | mTLS 자동 적용 (인증서 Istio 관리) |
| **http1MaxPendingRequests** | 100 | WAS CPU 250m-500m 고려 |
| **http2MaxRequests** | 100 | 동시 요청 수 제한 |
| **maxRequestsPerConnection** | 10 | HTTP Keep-Alive 재사용 제한 |
| **loadBalancer** | ROUND_ROBIN | 균등 분산 (HPA: 2-10 pods) |

**파일 위치:** `/home/jimin/k8s-manifests/blog-system/was-destinationrule.yaml`

---

## 4. 구현 과정 및 문제 해결

### 단계 1: Ingress 라우팅 변경

**목표:** `/api` 요청을 web-service로 라우팅하여 nginx proxy 활성화

**문제:**
- 기존: Ingress → was-service:8080 (mesh 우회)
- 목표: Ingress → web-service:80 → nginx → was-service (mesh 통과)

**해결:**
```bash
# blog-ingress.yaml 수정
vim /home/jimin/k8s-manifests/blog-system/blog-ingress.yaml
```

**변경 내용:**
```yaml
- path: /api
  backend:
    service:
      name: web-service  # 변경
      port:
        number: 80       # 변경
```

**Git 커밋:**
```bash
git add blog-system/blog-ingress.yaml
git commit -m "fix: Route /api through web-service for Istio mesh coverage"
git push

# Commit: 5ca0fb5
```

**ArgoCD Sync:**
```bash
argocd app sync blog-system
```

**검증:**
```bash
curl https://blog.jiminhome.shop/api/posts
# HTTP 200 OK ✅
```

**결과:**
- ✅ API 기능 정상 작동
- ⚠️ 하지만 Kiali에서 여전히 PassthroughCluster 표시

---

### 단계 2: nginx Host 헤더 수정

**목표:** Istio가 트래픽을 mesh 내부로 인식하도록 설정

**문제:**
- Kiali에서 모든 트래픽이 PassthroughCluster로 표시
- istio-proxy 로그: `PassthroughCluster` 반복

**원인 분석:**
```bash
# nginx config 확인
kubectl get cm -n blog-system web-nginx-config -o yaml | grep "proxy_set_header Host"
# proxy_set_header Host $host;  ← blog.jiminhome.shop (외부 도메인)
```

Istio의 판단 로직:
```
if Host header == 클러스터 내부 서비스명:
    → mesh 내부 트래픽 (mTLS 적용)
else:
    → PassthroughCluster (외부 트래픽, mTLS 없음)
```

**해결:**
```bash
vim /home/jimin/k8s-manifests/blog-system/web-nginx-config.yaml
```

**변경 내용:**
```nginx
location /api {
    # FQDN 사용
    proxy_pass http://was-service.blog-system.svc.cluster.local:8080;

    # Host 헤더를 서비스명으로 변경
    proxy_set_header Host was-service;  # ← 핵심 변경
}
```

**Git 커밋:**
```bash
git add blog-system/web-nginx-config.yaml
git commit -m "fix: Use FQDN and correct Host header for Istio mesh routing"
git push

# Commit: 6818ad7
```

**Pod 재시작 (ConfigMap 변경 적용):**
```bash
kubectl rollout restart deployment/web -n blog-system
kubectl rollout status deployment/web -n blog-system
```

**검증:**
```bash
# 1. API 기능 확인
curl https://blog.jiminhome.shop/api/posts
# HTTP 200 OK ✅

# 2. istio-proxy 로그 확인
kubectl logs -n blog-system deploy/web -c istio-proxy --tail=50 | grep was-service
# [2026-01-20] outbound|8080||was-service.blog-system.svc.cluster.local ✅
```

**결과:**
- ✅ API 기능 정상 작동
- ✅ istio-proxy 로그에서 mesh 라우팅 확인
- ⚠️ 하지만 Kiali에서 여전히 일부 PassthroughCluster

---

### 단계 3: DestinationRule 생성

**목표:** was-service에 mTLS 및 트래픽 정책 명시

**문제:**
- Host 헤더 수정 후에도 Kiali에서 PassthroughCluster 간헐적 발생
- mTLS 아이콘 미표시

**원인:**
```bash
# DestinationRule 확인
kubectl get destinationrule -n blog-system
# NAME             HOST          AGE
# web-dest-rule    web-service   3d  ← web만 존재
# (was-service용 없음)
```

Istio는 DestinationRule 없이도 동작하지만:
- mTLS 정책이 명시적이지 않음
- Connection Pool, Circuit Breaking 같은 고급 기능 미적용
- Kiali가 정책을 시각화할 수 없음

**해결:**
```bash
vim /home/jimin/k8s-manifests/blog-system/was-destinationrule.yaml
```

**파일 내용:**
```yaml
apiVersion: networking.istio.io/v1beta1
kind: DestinationRule
metadata:
  name: was-dest-rule
  namespace: blog-system
  labels:
    app: was
    tier: backend
spec:
  host: was-service

  trafficPolicy:
    tls:
      mode: ISTIO_MUTUAL  # mTLS 명시적 강제

    connectionPool:
      http:
        http1MaxPendingRequests: 100
        http2MaxRequests: 100
        maxRequestsPerConnection: 10

    loadBalancer:
      simple: ROUND_ROBIN
```

**Git 커밋:**
```bash
git add blog-system/was-destinationrule.yaml
git commit -m "feat: Add DestinationRule for was-service with mTLS"
git push

# Commit: cec7fe2
```

**ArgoCD Sync:**
```bash
argocd app sync blog-system
```

**검증:**
```bash
# 1. DestinationRule 생성 확인
kubectl get destinationrule -n blog-system was-dest-rule
# NAME            HOST          AGE
# was-dest-rule   was-service   10s ✅

# 2. API 기능 확인
curl https://blog.jiminhome.shop/api/posts
# HTTP 200 OK ✅

# 3. istio-proxy 로그 재확인
kubectl logs -n blog-system deploy/web -c istio-proxy --tail=50 | grep "outbound|8080"
# outbound|8080||was-service.blog-system.svc.cluster.local 10.0.1.101:32936 10.0.1.99:8080 ✅

# 4. 새로운 트래픽 생성 (Kiali 시각화용)
for i in {1..50}; do curl -s https://blog.jiminhome.shop/api/posts > /dev/null; done
```

**Kiali 확인:**
- Graph Type: **Workload graph**
- Time Range: **Last 10m**
- Display > Security: **Enabled**

**결과:**
```
web-service → web → was-service → was
     ↓                   ↓
  (녹색)             (녹색)

✅ 모든 연결이 녹색 (mesh 내부)
✅ PassthroughCluster 사라짐
```

---

## 5. 최종 검증

### 5.1 API 기능 테스트

```bash
# 외부 접근 (실제 사용자 경로)
curl https://blog.jiminhome.shop/api/posts
# HTTP/2 200
# [
#   {"id": 1, "title": "Test Post", ...}
# ] ✅

# 상세 응답 헤더 확인
curl -I https://blog.jiminhome.shop/api/posts
# HTTP/2 200
# content-type: application/json
# x-envoy-upstream-service-time: 45  ← Istio envoy 처리 시간 ✅
```

---

### 5.2 Istio mesh 라우팅 확인

```bash
# web pod의 istio-proxy 로그
kubectl logs -n blog-system deploy/web -c istio-proxy --tail=100 | grep "outbound|8080"

# 출력 예시:
# [2026-01-20T08:15:32.123Z] "GET /api/posts HTTP/1.1" 200 - via_upstream
# outbound|8080||was-service.blog-system.svc.cluster.local 10.0.1.101:32936 10.0.1.99:8080
#          ↑                                                      ↑                 ↑
#    was-service 포트                                   web pod IP            was pod IP
```

**확인 사항:**
- ✅ `outbound|8080||was-service.blog-system.svc.cluster.local` 출력
- ✅ PassthroughCluster 없음
- ✅ upstream 연결 성공

---

### 5.3 Kiali 시각화

#### Workload Graph 설정

1. **Graph Type**: Workload graph
   - 이유: Pod 레벨 연결을 보여줌 (web pod → was pod)

2. **Namespace**: blog-system

3. **Time Range**: Last 10m
   - 최근 트래픽만 표시

4. **Display Options**:
   - ✅ Traffic Animation
   - ✅ Security (mTLS 아이콘 표시)
   - ✅ Response Time

#### 예상 결과

```
┌──────────────┐
│ web-service  │
└──────┬───────┘
       │ (녹색, 굵은 선)
       ▼
┌──────────────┐
│     web      │ 🔒 mTLS
└──────┬───────┘
       │ (녹색, 굵은 선)
       ▼
┌──────────────┐
│ was-service  │
└──────┬───────┘
       │ (녹색, 굵은 선)
       ▼
┌──────────────┐
│     was      │ 🔒 mTLS
└──────┬───────┘
       │ (검정, 얇은 선 - mesh 제외)
       ▼
┌──────────────┐
│    mysql     │
└──────────────┘
```

**색상 의미:**
- **녹색**: Istio mesh 내부 트래픽 (mTLS 적용)
- **검정**: mesh 외부 또는 plain text
- **빨강**: 에러 발생

**아이콘 의미:**
- 🔒 (자물쇠): mTLS 암호화 적용

---

### 5.4 DestinationRule 정책 확인

```bash
# DestinationRule 상세 정보
kubectl get destinationrule -n blog-system was-dest-rule -o yaml

# 주요 확인 사항:
# - tls.mode: ISTIO_MUTUAL ✅
# - connectionPool 설정 ✅
# - loadBalancer: ROUND_ROBIN ✅
```

---

### 5.5 mTLS 인증서 확인

```bash
# was pod의 Envoy 인증서 확인
kubectl exec -n blog-system deploy/was -c istio-proxy -- \
  curl -s localhost:15000/certs | grep "Valid Until"

# 출력 예시:
# Certificate Chain
#   Valid Until: 2026-01-21T08:00:00Z  ← Istio가 자동 발급/갱신 ✅
```

---

## 6. 트러블슈팅 가이드

### 6.1 Kiali에서 PassthroughCluster로 표시

**증상:**
```
web → PassthroughCluster (검정색 선)
```

**진단 체크리스트:**

#### 1단계: nginx Host 헤더 확인
```bash
kubectl get cm -n blog-system web-nginx-config -o yaml | grep "proxy_set_header Host"
```

**예상 출력:**
```nginx
proxy_set_header Host was-service;  ✅
```

**잘못된 경우:**
```nginx
proxy_set_header Host $host;  ❌ → blog.jiminhome.shop (외부 도메인)
```

**해결:**
```nginx
proxy_set_header Host was-service;  # 서비스명으로 변경
```

---

#### 2단계: nginx proxy_pass FQDN 확인
```bash
kubectl get cm -n blog-system web-nginx-config -o yaml | grep "proxy_pass"
```

**예상 출력:**
```nginx
proxy_pass http://was-service.blog-system.svc.cluster.local:8080;  ✅
```

**잘못된 경우:**
```nginx
proxy_pass http://was-service:8080;  ⚠️ 짧은 이름 (동작하지만 비권장)
```

---

#### 3단계: DestinationRule 존재 확인
```bash
kubectl get destinationrule -n blog-system
```

**예상 출력:**
```
NAME            HOST          AGE
was-dest-rule   was-service   1d  ✅
web-dest-rule   web-service   3d  ✅
```

**누락된 경우:**
```yaml
# was-destinationrule.yaml 생성 필요
```

---

#### 4단계: istio-proxy 로그 확인
```bash
kubectl logs -n blog-system deploy/web -c istio-proxy --tail=100 | grep -E "(was-service|PassthroughCluster)"
```

**정상 출력:**
```
outbound|8080||was-service.blog-system.svc.cluster.local  ✅
```

**문제 출력:**
```
PassthroughCluster  ❌
```

---

### 6.2 502 Bad Gateway (STRICT mTLS)

**증상:**
```bash
curl https://blog.jiminhome.shop/
# HTTP/2 502
# upstream connect error or disconnect/reset before headers
```

**원인:**
- PeerAuthentication: `mode: STRICT`
- Nginx Ingress Controller가 plain text로 web-service:80 접근
- Istio가 mTLS 요구 → plain text 거부 → 502 에러

**진단:**
```bash
kubectl get peerauthentication -n blog-system default -o yaml | grep "mode"
# mode: STRICT  ❌
```

**해결 방법 1 (간단):**
```yaml
# mtls-peerauthentication.yaml
spec:
  mtls:
    mode: PERMISSIVE  # plain text + mTLS 둘 다 허용
```

**해결 방법 2 (권장 - 더 안전):**
```yaml
# mtls-peerauthentication.yaml
spec:
  mtls:
    mode: STRICT  # 기본은 STRICT

  # web-service:80만 예외 (Nginx Ingress 허용)
  portLevelMtls:
    80:
      mode: PERMISSIVE
```

**효과:**
| 구간 | 프로토콜 | 방법 1 | 방법 2 |
|------|----------|--------|--------|
| Ingress → web:80 | Plain text | ✅ 허용 | ✅ 허용 |
| web → was:8080 | mTLS | ⚠️ 선택적 | ✅ 강제 |
| was → mysql:3306 | Plain text | ✅ 허용 | ⚠️ 추가 설정 필요 |

---

### 6.3 Kiali에서 연결이 안 보임

**증상:**
- Kiali Graph가 비어있음
- 서비스만 표시되고 연결선이 없음

**원인 및 해결:**

#### 1단계: 트래픽 생성
```bash
# 최근 10분 내 트래픽이 없으면 안 보임
for i in {1..50}; do
  curl -s https://blog.jiminhome.shop/api/posts > /dev/null
  sleep 0.5
done
```

#### 2단계: Time Range 확인
- Kiali UI: Time Range → **Last 10m** 선택
- 트래픽이 오래된 경우 표시 안 됨

#### 3단계: Graph Type 변경
- **Versioned app graph**: Argo Rollouts의 canary/stable 버전 구분
- **Workload graph**: Pod 레벨 연결 (권장)
- **App graph**: 애플리케이션 레벨

**권장:**
```
Workload graph + Last 10m + Display > Security ✅
```

#### 4단계: Namespace 확인
- Kiali UI: Namespace → **blog-system** 선택
- 다른 namespace 선택 시 안 보임

---

### 6.4 nginx config 변경이 적용 안 됨

**증상:**
```bash
# ConfigMap은 수정했는데 nginx에 반영 안 됨
kubectl get cm -n blog-system web-nginx-config -o yaml  # ✅ 수정됨
kubectl exec -n blog-system deploy/web -- cat /etc/nginx/conf.d/default.conf  # ❌ 이전 내용
```

**원인:**
- ConfigMap 변경은 **기존 Pod에 자동 반영 안 됨**
- Pod를 재시작해야 함

**해결:**
```bash
# 방법 1: Deployment 재시작 (권장)
kubectl rollout restart deployment/web -n blog-system
kubectl rollout status deployment/web -n blog-system

# 방법 2: Pod 직접 삭제 (비권장)
kubectl delete pod -n blog-system -l app=web

# 방법 3: ArgoCD Sync (GitOps)
argocd app sync blog-system
```

**검증:**
```bash
# nginx config 재확인
kubectl exec -n blog-system deploy/web -- cat /etc/nginx/conf.d/default.conf | grep "proxy_set_header Host"
# proxy_set_header Host was-service;  ✅
```

---

### 6.5 ArgoCD Out of Sync

**증상:**
```bash
argocd app get blog-system
# Status:      OutOfSync  ❌
```

**원인:**
- Git 저장소의 manifest와 클러스터 상태 불일치
- 수동 kubectl 수정 (ArgoCD가 selfHeal로 되돌림)

**해결:**
```bash
# 방법 1: Git → 클러스터 동기화 (권장)
argocd app sync blog-system

# 방법 2: 수동 수정 허용 (일시적)
kubectl label -n blog-system configmap web-nginx-config \
  argocd.argoproj.io/compare=IgnoreExtraneous

# 방법 3: selfHeal 비활성화 (비권장)
argocd app set blog-system --self-heal=false
```

**검증:**
```bash
argocd app get blog-system
# Status:      Synced  ✅
# Health:      Healthy  ✅
```

---

## 7. 다음 단계 (고도화 옵션)

### 우선순위 결정 가이드

| 개선 항목 | 난이도 | 효과 | 시간 | 추천 시나리오 |
|-----------|--------|------|------|---------------|
| **1. web DestinationRule 개선** | ⭐ 쉬움 | ⭐⭐⭐ 높음 | 10분 | ✅ 모든 환경 필수 |
| **2. AuthorizationPolicy** | ⭐⭐ 보통 | ⭐⭐⭐ 높음 | 15분 | ✅ 프로덕션 필수 |
| **3. STRICT mTLS (portLevelMtls)** | ⭐ 쉬움 | ⭐⭐ 중간 | 5분 | 🤔 규제 준수 시 |
| **4. VirtualService 고도화** | ⭐⭐ 보통 | ⭐⭐ 중간 | 20분 | 🤔 Resilience 강화 |
| **5. Traffic Mirroring** | ⭐⭐ 보통 | ⭐⭐ 중간 | 15분 | 🤔 무위험 canary 테스트 |
| **6. 분산 추적 (Jaeger)** | ⭐⭐⭐ 어려움 | ⭐⭐⭐ 높음 | 30분 | 🤔 성능 병목 분석 |

---

### ⏳ 즉시 적용 가능 (30분) - 프로덕션급 보안

#### 1. web-destinationrule 개선 (10분)

**현재 문제:**
- web-destinationrule은 **subset만 정의** (Argo Rollouts 용도)
- traffic policy 없음 (Connection Pool, Circuit Breaking 미적용)
- was-service는 정책 있는데 web-service는 없음 (불균형)

**개선 효과:**
- Circuit Breaking: 장애 Pod 자동 제외
- Connection Pool: nginx 과부하 방지
- 일관된 트래픽 정책 (web, was 모두 적용)

**구현:**
```yaml
# blog-system/web-destinationrule.yaml
apiVersion: networking.istio.io/v1beta1
kind: DestinationRule
metadata:
  name: web-dest-rule
  namespace: blog-system
spec:
  host: web-service

  # 🆕 Traffic Policy 추가
  trafficPolicy:
    tls:
      mode: ISTIO_MUTUAL

    connectionPool:
      http:
        http1MaxPendingRequests: 100
        http2MaxRequests: 100
        maxRequestsPerConnection: 10
      tcp:
        maxConnections: 100

    loadBalancer:
      simple: ROUND_ROBIN

    # 🆕 Outlier Detection (Circuit Breaking)
    outlierDetection:
      consecutive5xxErrors: 5      # 5번 연속 5xx
      interval: 10s                 # 10초마다 체크
      baseEjectionTime: 30s         # 30초간 제외
      maxEjectionPercent: 50        # 최대 50% Pod 제외
      minHealthPercent: 30          # 최소 30% Pod 유지

  # 기존 subset 유지
  subsets:
  - name: stable
    labels: {}
  - name: canary
    labels: {}
```

**검증:**
```bash
kubectl apply -f blog-system/web-destinationrule.yaml
kubectl get destinationrule -n blog-system web-dest-rule -o yaml
```

---

#### 2. AuthorizationPolicy 추가 (15분)

**현재 문제:**
- 모든 서비스가 모든 서비스에 접근 가능 (Zero Trust 위반)
- 예: 외부에서 was-service:8080 직접 호출 가능 (이론상)

**보안 원칙:**
```
✅ 허용:
- Ingress → web-service:80
- web → was-service:8080
- was → mysql:3306

❌ 거부:
- 외부 → was-service:8080 (직접 접근)
- web → mysql:3306 (계층 우회)
- was → web (역방향)
```

**구현:**

```yaml
# blog-system/authz-web.yaml (신규)
apiVersion: security.istio.io/v1beta1
kind: AuthorizationPolicy
metadata:
  name: web-authz
  namespace: blog-system
spec:
  selector:
    matchLabels:
      app: web
  action: ALLOW
  rules:
  # Ingress Gateway에서의 접근 허용
  - from:
    - source:
        namespaces: ["istio-system"]
    to:
    - operation:
        ports: ["80"]
```

```yaml
# blog-system/authz-was.yaml (신규)
apiVersion: security.istio.io/v1beta1
kind: AuthorizationPolicy
metadata:
  name: was-authz
  namespace: blog-system
spec:
  selector:
    matchLabels:
      app: was
  action: ALLOW
  rules:
  # web pod에서만 접근 허용
  - from:
    - source:
        principals: ["cluster.local/ns/blog-system/sa/default"]
        namespaces: ["blog-system"]
    to:
    - operation:
        ports: ["8080"]
        paths: ["/api/*", "/actuator/*"]  # 허용 경로 명시
```

**검증:**
```bash
kubectl apply -f blog-system/authz-web.yaml
kubectl apply -f blog-system/authz-was.yaml

# 정상 접근 (허용)
curl https://blog.jiminhome.shop/api/posts
# 200 OK ✅

# 비정상 접근 테스트 (차단 확인 - 클러스터 내부에서)
kubectl run -it --rm debug --image=curlimages/curl --restart=Never -- \
  curl http://was-service.blog-system.svc.cluster.local:8080/api/posts
# RBAC: access denied  ✅
```

---

#### 3. STRICT mTLS with portLevelMtls (5분)

**현재 문제:**
- PeerAuthentication: `PERMISSIVE` (모든 포트가 plain text + mTLS 허용)
- was-service:8080도 plain text 허용 (불필요하게 느슨함)

**개선 효과:**
- was-service:8080 → **mTLS 강제**
- web-service:80 → PERMISSIVE (Nginx Ingress 호환)
- mysql:3306 → plain text (JDBC 호환)

**구현:**
```yaml
# blog-system/mtls-peerauthentication.yaml
apiVersion: security.istio.io/v1beta1
kind: PeerAuthentication
metadata:
  name: default
  namespace: blog-system
spec:
  mtls:
    mode: STRICT  # 기본은 STRICT

  # 포트별 예외 설정
  portLevelMtls:
    80:
      mode: PERMISSIVE  # web-service:80 (Nginx Ingress)
    3306:
      mode: DISABLE     # mysql:3306 (JDBC)
```

**주의사항:**
```bash
# mysql이 mesh에 포함되어 있다면 sidecar 제외 필요
kubectl patch deployment mysql -n blog-system -p '
{
  "spec": {
    "template": {
      "metadata": {
        "annotations": {
          "sidecar.istio.io/inject": "false"
        }
      }
    }
  }
}'
```

**검증:**
```bash
kubectl apply -f blog-system/mtls-peerauthentication.yaml

# 외부 접근 (허용)
curl https://blog.jiminhome.shop/
# 200 OK ✅

# was-service mTLS 강제 확인
kubectl logs -n blog-system deploy/web -c istio-proxy --tail=50 | grep "outbound|8080"
# mTLS 연결 확인 ✅
```

---

### 🔜 선택 사항 (1-2시간) - 고급 기능

#### 4. VirtualService 고도화 (20분)

**추가 기능:**
- Retry 정책: 일시적 네트워크 오류 복구
- Timeout: 무한 대기 방지
- 헤더 기반 카나리 라우팅: 관리자만 canary 테스트

**구현:**
```yaml
# blog-system/web-virtualservice.yaml
apiVersion: networking.istio.io/v1beta1
kind: VirtualService
metadata:
  name: web-vsvc
  namespace: blog-system
spec:
  hosts:
  - web-service

  http:
  # 🆕 관리자 트래픽: 항상 canary
  - name: canary-testing
    match:
    - headers:
        x-canary-test:
          exact: "true"
    route:
    - destination:
        host: web-service
        subset: canary
      weight: 100

  # 일반 트래픽 (Argo Rollouts가 weight 조정)
  - name: primary
    route:
    - destination:
        host: web-service
        subset: stable
      weight: 100
    - destination:
        host: web-service
        subset: canary
      weight: 0

    # 🆕 Retry 정책
    retries:
      attempts: 3
      perTryTimeout: 2s
      retryOn: 5xx,reset,connect-failure,refused-stream

    # 🆕 Timeout
    timeout: 10s
```

**테스트:**
```bash
# 일반 사용자: stable 버전
curl https://blog.jiminhome.shop/

# 관리자: canary 버전
curl -H "x-canary-test: true" https://blog.jiminhome.shop/
```

---

#### 5. Traffic Mirroring (15분)

**목적:**
- canary 버전에 트래픽 복사
- 응답 버림 (사용자 영향 0%)
- 프로덕션 환경에서 무위험 테스트

**구현:**
```yaml
# blog-system/web-virtualservice.yaml
spec:
  http:
  - route:
    - destination:
        host: web-service
        subset: stable
      weight: 100

    # 🆕 Shadow Traffic
    mirror:
      host: web-service
      subset: canary
    mirrorPercentage:
      value: 100.0  # stable 트래픽의 100%를 canary에 복사
```

**효과:**
| 배포 방식 | 사용자 영향 | 테스트 범위 |
|-----------|-------------|-------------|
| **기존 Canary** | 10% 사용자 | 실제 트래픽 |
| **Mirroring** | 0% 사용자 | 실제 트래픽 |

---

#### 6. 분산 추적 (Jaeger) (30분)

**목적:**
- 요청별 전체 흐름 추적 (ms 단위)
- 병목 구간 즉시 발견 (web nginx? was? mysql?)

**설치:**
```bash
# Jaeger 설치
kubectl apply -f https://raw.githubusercontent.com/istio/istio/release-1.20/samples/addons/jaeger.yaml

# Kiali에서 Jaeger 연동
kubectl patch configmap kiali -n istio-system -p '
{
  "data": {
    "external_services.tracing.url": "http://jaeger-query.istio-system:16686"
  }
}'
```

**결과:**
- Kiali에서 "Traces" 탭 활성화
- 요청 클릭 → Jaeger에서 상세 분석

```
[Request ID: abc123]
├─ Nginx Ingress: 10ms
├─ web nginx: 50ms
├─ was: 200ms
└─ mysql: 4700ms  ← 병목 발견!
```

---

### 체크리스트

#### ✅ 구축 완료 (현재)
- [x] Ingress → web-service 라우팅
- [x] nginx proxy → was-service (FQDN + Host 헤더)
- [x] DestinationRule with mTLS (was-service)
- [x] API 기능 검증 (200 OK)
- [x] Kiali 시각화 (Workload graph)
- [x] istio-proxy 로그 확인

#### ⏳ 즉시 적용 가능 (30분)
- [ ] **web-destinationrule 개선** (Circuit Breaking 추가)
- [ ] **AuthorizationPolicy 추가** (Zero Trust 보안)
- [ ] **STRICT mTLS with portLevelMtls** (was 강제 암호화)

#### 🔜 선택 사항 (1-2시간)
- [ ] VirtualService 고도화 (Retry, Timeout, 헤더 라우팅)
- [ ] Traffic Mirroring (무위험 canary 테스트)
- [ ] 분산 추적 (Jaeger 설치 및 연동)

---

## 부록: Git 커밋 히스토리

```bash
# Istio mesh 구현 관련 커밋
git log --oneline --all | grep -E "(mesh|mTLS|DestinationRule|Istio)"

# cec7fe2 - feat: Add DestinationRule for was-service with mTLS
# 6818ad7 - fix: Use FQDN and correct Host header for Istio mesh routing
# 5ca0fb5 - fix: Route /api through web-service for Istio mesh coverage
# 0b8d573 - Fix: Change mTLS mode from STRICT to PERMISSIVE for Ingress access
# f33587a - fix: Allow plain TCP for MySQL (JDBC compatibility)
# e2de671 - feat: Add Istio Service Mesh policies
```

---

## 부록: 주요 명령어 모음

### Kiali 접속
```bash
# Kiali 포트포워딩
kubectl port-forward -n istio-system svc/kiali 20001:20001

# 브라우저에서 접속
open http://localhost:20001
```

### Istio 리소스 조회
```bash
# DestinationRule 목록
kubectl get destinationrule -n blog-system

# VirtualService 목록
kubectl get virtualservice -n blog-system

# PeerAuthentication 확인
kubectl get peerauthentication -n blog-system

# AuthorizationPolicy 목록 (고도화 후)
kubectl get authorizationpolicy -n blog-system
```

### istio-proxy 로그
```bash
# web pod의 istio-proxy 로그
kubectl logs -n blog-system deploy/web -c istio-proxy --tail=100

# was pod의 istio-proxy 로그
kubectl logs -n blog-system deploy/was -c istio-proxy --tail=100

# 실시간 로그 (follow)
kubectl logs -n blog-system deploy/web -c istio-proxy -f | grep "outbound|8080"
```

### 트래픽 생성 (테스트용)
```bash
# 50회 요청
for i in {1..50}; do
  curl -s https://blog.jiminhome.shop/api/posts > /dev/null
  echo "Request $i completed"
  sleep 0.5
done
```

---

**작성일**: 2026-01-20
**작성자**: Claude + Jimin
**문서 버전**: 1.0
**다음 작업**: 고도화 옵션 선택 및 적용 (1, 2, 3번 권장)
