# Istio 고도화 작업 목록

> nginx proxy Istio mesh 구현 완료 후 추가 작업

**작성일**: 2026-01-20
**현재 상태**: ✅ 기본 mesh 구현 완료 (mTLS, Kiali 시각화)

---

## ⏳ 즉시 적용 권장 (30분) - 프로덕션급 보안

### 1. web-destinationrule 개선 (10분) ⭐⭐⭐

**목표:** Circuit Breaking 추가하여 장애 Pod 자동 제외

**현재 문제:**
- web-destinationrule은 subset만 정의 (traffic policy 없음)
- was-service는 정책 있는데 web-service는 없음 (불균형)

**작업 내용:**
```bash
vim blog-system/web-destinationrule.yaml
```

**추가할 정책:**
- ✅ `trafficPolicy.tls.mode: ISTIO_MUTUAL`
- ✅ `connectionPool` (http: 100, tcp: 100)
- ✅ `outlierDetection` (5xx 5번 → 30초 제외)
- ✅ `loadBalancer: ROUND_ROBIN`

**검증:**
```bash
kubectl apply -f blog-system/web-destinationrule.yaml
kubectl get destinationrule -n blog-system web-dest-rule -o yaml
```

**기대 효과:**
- 5xx 에러 5번 → 해당 Pod 30초간 트래픽 차단
- 건강한 Pod로만 요청 전달 → 사용자 영향 최소화

**파일 위치:** `/home/jimin/k8s-manifests/blog-system/web-destinationrule.yaml`

---

### 2. AuthorizationPolicy 추가 (15분) ⭐⭐⭐

**목표:** Zero Trust 보안 - 최소 권한 원칙 적용

**현재 문제:**
- 모든 서비스가 모든 서비스에 접근 가능
- 외부에서 was-service:8080 직접 호출 가능 (이론상)

**작업 내용:**
```bash
# 2개 파일 생성
vim blog-system/authz-web.yaml
vim blog-system/authz-was.yaml
```

**보안 규칙:**
```
✅ 허용:
- istio-system (Ingress) → web-service:80
- web → was-service:8080 (/api/*, /actuator/*)

❌ 거부:
- 외부 → was-service:8080
- web → mysql:3306
- was → web (역방향)
```

**authz-web.yaml:**
```yaml
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
  - from:
    - source:
        namespaces: ["istio-system"]
    to:
    - operation:
        ports: ["80"]
```

**authz-was.yaml:**
```yaml
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
  - from:
    - source:
        principals: ["cluster.local/ns/blog-system/sa/default"]
        namespaces: ["blog-system"]
    to:
    - operation:
        ports: ["8080"]
        paths: ["/api/*", "/actuator/*"]
```

**검증:**
```bash
kubectl apply -f blog-system/authz-web.yaml
kubectl apply -f blog-system/authz-was.yaml

# 정상 접근 (허용)
curl https://blog.jiminhome.shop/api/posts
# 200 OK ✅

# 비정상 접근 (차단)
kubectl run -it --rm debug --image=curlimages/curl --restart=Never -- \
  curl http://was-service.blog-system.svc.cluster.local:8080/api/posts
# RBAC: access denied ✅
```

**기대 효과:**
- Defense in Depth (다층 방어)
- 규제 준수 (Zero Trust 아키텍처)
- 공격 표면 최소화

**파일 위치:**
- `/home/jimin/k8s-manifests/blog-system/authz-web.yaml` (신규)
- `/home/jimin/k8s-manifests/blog-system/authz-was.yaml` (신규)

---

### 3. STRICT mTLS with portLevelMtls (5분) ⭐⭐

**목표:** was-service:8080 mTLS 강제 (보안 강화)

**현재 문제:**
- PeerAuthentication: PERMISSIVE (모든 포트가 plain text 허용)
- was-service:8080도 plain text 가능 (불필요하게 느슨함)

**작업 내용:**
```bash
vim blog-system/mtls-peerauthentication.yaml
```

**변경 내용:**
```yaml
apiVersion: security.istio.io/v1beta1
kind: PeerAuthentication
metadata:
  name: default
  namespace: blog-system
spec:
  mtls:
    mode: STRICT  # 기본은 STRICT (변경)

  # 포트별 예외 설정
  portLevelMtls:
    80:
      mode: PERMISSIVE  # web-service:80만 예외
    3306:
      mode: DISABLE     # mysql:3306 (JDBC)
```

**주의사항:**
```bash
# mysql이 mesh에 포함되어 있다면 sidecar 제외 필요
kubectl get pod -n blog-system -l app=mysql -o jsonpath='{.items[0].spec.containers[*].name}'

# istio-proxy가 있으면:
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

# was mTLS 확인
kubectl logs -n blog-system deploy/web -c istio-proxy --tail=50 | grep "outbound|8080"
# mTLS 연결 확인 ✅
```

**기대 효과:**

| 구간 | Before | After |
|------|--------|-------|
| Ingress → web:80 | Plain text | Plain text (PERMISSIVE) |
| web → was:8080 | ⚠️ Plain text 가능 | 🔒 mTLS 강제 (STRICT) |
| was → mysql:3306 | Plain text | Plain text (DISABLE) |

**파일 위치:** `/home/jimin/k8s-manifests/blog-system/mtls-peerauthentication.yaml`

---

## 🔜 선택 사항 (1-2시간) - 고급 기능

### 4. VirtualService 고도화 (20분) ⭐⭐

**목표:** Retry, Timeout, 헤더 기반 카나리 라우팅

**추가 기능:**
- ✅ Retry 정책: 일시적 네트워크 오류 복구 (3회 재시도)
- ✅ Timeout: 무한 대기 방지 (10초)
- ✅ 헤더 기반 라우팅: 관리자만 canary 테스트

**작업 내용:**
```bash
vim blog-system/web-virtualservice.yaml
```

**추가할 설정:**
```yaml
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

# 일반 트래픽
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

**트레이드오프:**
- 장점: 일시적 오류 자동 복구, 무한 대기 방지
- 단점: 지연 시간 증가 (최대 6초 - 3회 재시도)

**파일 위치:** `/home/jimin/k8s-manifests/blog-system/web-virtualservice.yaml`

---

### 5. Traffic Mirroring (15분) ⭐⭐

**목표:** 무위험 canary 테스트 (사용자 영향 0%)

**현재 문제:**
- Argo Rollouts canary: 10% 사용자가 실험 대상
- 에러 발생 시 사용자 영향

**작업 내용:**
```bash
vim blog-system/web-virtualservice.yaml
```

**추가할 설정:**
```yaml
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

**실전 시나리오:**
```
1. Mirroring 활성화 (canary 배포)
2. Grafana/Prometheus로 canary 모니터링
   - 에러율, 지연시간, 메모리 사용량
3. 문제 없으면: Argo Rollouts로 실제 canary 10% 전환
4. 문제 있으면: Mirroring만 중단 (사용자 영향 0%)
```

**비교:**

| 배포 방식 | 사용자 영향 | 테스트 범위 | 롤백 속도 |
|-----------|-------------|-------------|-----------|
| **기존 Canary (10%)** | 10% 사용자 | 실제 트래픽 | 수동 롤백 |
| **Mirroring** | 0% 사용자 | 실제 트래픽 | 즉시 중단 |
| **Mirroring + Canary** | 최소화 | 이중 검증 | 최고 |

**파일 위치:** `/home/jimin/k8s-manifests/blog-system/web-virtualservice.yaml`

---

### 6. 분산 추적 (Jaeger) (30분) ⭐⭐⭐

**목표:** 요청별 전체 흐름 추적 및 병목 구간 분석

**현재 문제:**
- Kiali는 서비스 간 연결만 보여줌
- 어떤 요청이 느린지 모름 (web? was? mysql?)

**작업 내용:**

**1단계: Jaeger 설치 (5분)**
```bash
kubectl apply -f https://raw.githubusercontent.com/istio/istio/release-1.20/samples/addons/jaeger.yaml

# 포트포워딩
kubectl port-forward -n istio-system svc/jaeger-query 16686:16686

# 브라우저 접속
open http://localhost:16686
```

**2단계: Istio에 Jaeger 연동 (10분)**
```bash
# Istio ConfigMap 수정
kubectl edit configmap istio -n istio-system

# 추가할 내용:
meshConfig:
  enableTracing: true
  defaultConfig:
    tracing:
      zipkin:
        address: jaeger-collector.istio-system.svc:9411
```

**3단계: Kiali 연동 (5분)**
```bash
kubectl patch configmap kiali -n istio-system -p '
{
  "data": {
    "external_services.tracing.enabled": "true",
    "external_services.tracing.url": "http://jaeger-query.istio-system:16686"
  }
}'

# Kiali 재시작
kubectl rollout restart deployment kiali -n istio-system
```

**4단계: 테스트 (10분)**
```bash
# 트래픽 생성
for i in {1..20}; do
  curl -s https://blog.jiminhome.shop/api/posts > /dev/null
done

# Jaeger UI에서 확인
# Service: web-service 선택
# Operation: /api/posts 선택
```

**결과 예시:**
```
[Request ID: abc123]  총 5초
├─ Nginx Ingress: 10ms
├─ web nginx: 50ms
├─ was: 200ms
└─ mysql: 4700ms  ← 병목 발견! (94%)
```

**기대 효과:**
- 요청별 상세 추적 (ms 단위)
- 병목 구간 즉시 발견
- 성능 최적화 우선순위 결정
- Kiali에서 "Traces" 탭 활성화

**트레이드오프:**
- 장점: 정확한 성능 분석, 병목 발견
- 단점: Tracing 오버헤드 (약 1-2% CPU), 스토리지 사용

**참고 문서:**
- https://istio.io/latest/docs/tasks/observability/distributed-tracing/jaeger/
- https://www.jaegertracing.io/docs/

---

## 체크리스트

### ✅ 완료 (현재 상태)
- [x] Ingress → web-service 라우팅
- [x] nginx proxy → was-service (FQDN + Host 헤더)
- [x] was-destinationrule with mTLS
- [x] API 기능 검증 (200 OK)
- [x] Kiali 시각화 (Workload graph)
- [x] istio-proxy 로그 확인
- [x] 문서화 (NGINX-PROXY-ISTIO-MESH.md)

### ⏳ 즉시 적용 권장 (30분)
- [ ] **1. web-destinationrule 개선** (Circuit Breaking)
- [ ] **2. AuthorizationPolicy 추가** (Zero Trust)
- [ ] **3. STRICT mTLS with portLevelMtls** (보안 강화)

### 🔜 선택 사항 (1-2시간)
- [ ] **4. VirtualService 고도화** (Retry, Timeout, 헤더 라우팅)
- [ ] **5. Traffic Mirroring** (무위험 canary)
- [ ] **6. 분산 추적 (Jaeger)** (성능 병목 분석)

---

## 우선순위 결정 가이드

### 프로덕션 환경 (1, 2, 3번 필수)
```
보안 + 안정성 중시
→ 1. Circuit Breaking
→ 2. AuthorizationPolicy
→ 3. STRICT mTLS
```

### 카나리 배포 고도화 (4, 5번)
```
무중단 배포 + 무위험 테스트 중시
→ 4. VirtualService Retry/Timeout
→ 5. Traffic Mirroring
```

### 성능 최적화 (6번)
```
병목 분석 + 최적화 필요
→ 6. Jaeger 분산 추적
```

---

## Git 작업 흐름

### 개선 작업 시
```bash
# 파일 수정
vim blog-system/web-destinationrule.yaml

# Git 커밋
git add blog-system/web-destinationrule.yaml
git commit -m "feat: Add Circuit Breaking to web-destinationrule"
git push

# ArgoCD 동기화
argocd app sync blog-system

# 검증
kubectl get destinationrule -n blog-system web-dest-rule -o yaml
```

### 롤백 시
```bash
# 이전 커밋으로 롤백
git revert HEAD
git push

# ArgoCD 동기화
argocd app sync blog-system
```

---

## 관련 문서

- [NGINX-PROXY-ISTIO-MESH.md](./NGINX-PROXY-ISTIO-MESH.md) - 구현 완전 가이드
- [Istio DestinationRule 공식 문서](https://istio.io/latest/docs/reference/config/networking/destination-rule/)
- [Istio AuthorizationPolicy 공식 문서](https://istio.io/latest/docs/reference/config/security/authorization-policy/)
- [Istio Traffic Management](https://istio.io/latest/docs/concepts/traffic-management/)

---

**작성일**: 2026-01-20
**다음 업데이트**: 작업 완료 시 체크리스트 업데이트
**추천 순서**: 1 → 2 → 3 → (선택) 4, 5, 6
