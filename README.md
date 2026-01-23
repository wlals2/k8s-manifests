# k8s-manifests

> Kubernetes manifest repository for ArgoCD GitOps

## Structure

```
blog-system/
# Frontend
├── web-rollout.yaml             # Hugo 블로그 (nginx) - Argo Rollouts Canary
├── web-nginx-config.yaml        # Nginx ConfigMap (/api → was-service 프록시)
├── web-service.yaml             # ClusterIP Service
├── web-virtualservice.yaml      # Istio VirtualService (stable/canary)
├── web-destinationrule.yaml     # Istio DestinationRule (subsets)

# Backend
├── was-deployment.yaml          # Spring Boot WAS
├── was-service.yaml             # ClusterIP Service
├── was-configmap.yaml           # WAS 설정
├── was-retry-timeout.yaml       # Istio Retry & Timeout 정책

# Database
├── mysql-deployment.yaml        # MySQL 8.0 (Istio mesh 제외)
├── mysql-service.yaml           # ClusterIP Service
├── mysql-pvc.yaml               # PersistentVolumeClaim (Longhorn)
├── mysql-circuit-breaker.yaml   # Istio Circuit Breaker
├── mysql-mtls-exception.yaml    # MySQL mTLS 예외 (PERMISSIVE)

# Ingress & Security
├── blog-ingress.yaml            # Nginx Ingress (blog.jiminhome.shop)
├── mtls-peerauthentication.yaml # Istio mTLS 정책 (PERMISSIVE)
└── mysql-exporter.yaml          # Prometheus MySQL Exporter
```

## Architecture

### Traffic Flow (Istio Service Mesh)

```
[외부 사용자]
      ↓
[Nginx Ingress] (192.168.X.200)
      ↓ (모든 경로)
[web-service] ClusterIP
      ↓
[web pod - nginx + istio-proxy]
      ├─ / → 정적 파일 (Hugo)
      └─ /api/ → was-service:8080 (Istio mesh 통과 🔒)
              ↓ mTLS 암호화
        [was-service] ClusterIP
              ↓
        [was pod - Spring Boot + istio-proxy]
              ↓ 평문 TCP (MySQL은 mesh 제외)
        [mysql-service] ClusterIP
              ↓
        [mysql pod - MySQL 8.0]
```

### Istio Service Mesh 기능

| 기능 | 적용 대상 | 설정 파일 | 효과 |
|------|----------|----------|------|
| **mTLS** | web ↔ was | mtls-peerauthentication.yaml | 🔒 자동 암호화 |
| **Circuit Breaking** | was → mysql | mysql-circuit-breaker.yaml | 과부하 방지 |
| **Retry & Timeout** | web → was | was-retry-timeout.yaml | 장애 복구 |
| **Canary Deployment** | web | web-rollout.yaml | 점진적 배포 |
| **Observability** | 전체 | Kiali, Jaeger, Prometheus | 시각화 |

### Argo Rollouts Canary Strategy

**web-rollout.yaml**:
```
Canary Steps:
1. 10% 트래픽 → 30초 대기
2. 50% 트래픽 → 30초 대기
3. 90% 트래픽 → 30초 대기
4. 100% 트래픽 → 배포 완료

Istio Integration:
- VirtualService: 트래픽 가중치 자동 조정
- DestinationRule: stable/canary subset 관리
```

### MySQL Istio 제외 이유

**문제**: MySQL JDBC 드라이버는 Istio mTLS와 호환되지 않음
- JDBC는 평문 TCP/IP 연결 사용
- Istio sidecar가 mTLS 협상 시도 → 연결 실패

**해결**:
1. **mysql-deployment.yaml**: `sidecar.istio.io/inject: "false"` (sidecar 주입 제외)
2. **mysql-mtls-exception.yaml**: `mode: PERMISSIVE` (평문 허용)

## ArgoCD Application

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: blog-system
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/wlals2/k8s-manifests.git
    targetRevision: main
    path: blog-system
  destination:
    server: https://kubernetes.default.svc
    namespace: blog-system
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
```

## 🔒 Secret 관리

### ⚠️ 보안 주의사항

**Secret 파일은 Git에 커밋되지 않습니다!**

`.gitignore`에 `*-secret.yaml` 패턴이 추가되어 있어 Secret 파일이 자동으로 제외됩니다.

### MySQL Secret 생성

ArgoCD Application 생성 **전에** Secret을 수동으로 생성해야 합니다:

```bash
# mysql-secret.yaml 파일 생성
cat <<EOF > blog-system/mysql-secret.yaml
apiVersion: v1
kind: Secret
metadata:
  name: mysql-secret
  namespace: blog-system
  labels:
    app: mysql
type: Opaque
stringData:
  mysql-root-password: "YOUR_ROOT_PASSWORD"
  mysql-password: "YOUR_USER_PASSWORD"
EOF

# Secret 적용
kubectl apply -f blog-system/mysql-secret.yaml

# Secret 확인
kubectl get secret mysql-secret -n blog-system
```

### 왜 Secret을 Git에 넣지 않나요?

| 방식 | 장점 | 단점 | 선택 |
|------|------|------|------|
| **평문 Git 저장** | 간단함 | ❌ **보안 위험 심각** | ❌ |
| **Secret 제외 (.gitignore)** | 간단, 안전 | 수동 생성 필요 | ✅ **선택** |
| **Sealed Secrets** | Git 저장 가능 | 복잡한 설정 필요 | 미래 |
| **External Secrets** | 중앙 관리 | Vault 등 추가 인프라 | 미래 |

**현재 방식**: Secret은 `.gitignore`로 제외하고, 클러스터에 수동으로 생성

**장점:**
- ✅ 보안: Git에 비밀번호 노출 없음
- ✅ 단순: 추가 도구 불필요
- ✅ 유연: 환경별 다른 비밀번호 사용 가능

**단점:**
- ❌ 수동 작업: 클러스터마다 Secret 생성 필요
- ❌ 백업: Secret은 별도로 안전하게 보관해야 함

## Deployment

ArgoCD가 이 저장소를 감시하고 자동으로 Kubernetes에 동기화합니다.

**변경 방법:**
1. manifest 파일 수정
2. `git commit` & `git push`
3. ArgoCD가 자동으로 감지 (3초 이내)
4. Kubernetes 자동 동기화

**예시 1: Replicas 변경**
```bash
# replicas 변경
vi blog-system/web-rollout.yaml
# replicas: 2 → 3

git add blog-system/web-rollout.yaml
git commit -m "scale: web replicas 2 → 3"
git push

# ArgoCD 자동 동기화 확인
kubectl get pods -n blog-system
# web-xxx-1, web-xxx-2, web-xxx-3 (3개로 증가)
```

**예시 2: Canary 배포 (이미지 변경)**
```bash
# 이미지 태그 변경
vi blog-system/web-rollout.yaml
# image: ghcr.io/wlals2/blog-web:v11 → v12

git add blog-system/web-rollout.yaml
git commit -m "deploy: web v11 → v12"
git push

# Argo Rollouts Canary 배포 확인
kubectl argo rollouts get rollout web -n blog-system
# Step 1/7: Canary 10%, Stable 90%
# Step 3/7: Canary 50%, Stable 50%
# Step 5/7: Canary 90%, Stable 10%
# Step 7/7: Canary 100% (배포 완료)

# 수동 승인 (필요 시)
kubectl argo rollouts promote web -n blog-system
```

## Observability

### Kiali (Service Mesh 시각화)
```bash
# Kiali 접속
http://kiali.jiminhome.shop

# Graph 설정
- Graph Type: Workload graph
- Display 옵션:
  ✅ Security (mTLS 🔒 아이콘)
  ✅ Traffic Distribution (트래픽 비율 %)
  ✅ Traffic Rate (RPS)
  ✅ Traffic Animation (흐름 애니메이션)
```

### Jaeger (분산 추적)
```bash
# Jaeger 접속
http://jaeger.jiminhome.shop

# 트레이스 조회
Service: web.blog-system
Operation: /api/boards
```

## Troubleshooting

### WAS CrashLoopBackOff (MySQL 연결 실패)
**증상**: `Communications link failure`, `SocketTimeoutException`

**원인**: Istio mTLS STRICT 모드가 MySQL JDBC와 충돌

**해결**:
```bash
# MySQL을 Istio mesh에서 제외
kubectl get deployment mysql -n blog-system -o yaml | grep "sidecar.istio.io/inject"
# annotations:
#   sidecar.istio.io/inject: "false"

# MySQL mTLS PERMISSIVE 모드 확인
kubectl get peerauthentication mysql-mtls-exception -n blog-system
# mode: PERMISSIVE (평문 TCP 허용)
```

### Kiali에서 트래픽이 안 보임
**원인**: 트래픽이 없거나, Display 옵션이 비활성화됨

**해결**:
```bash
# 트래픽 생성
for i in {1..50}; do
  curl -s http://blog.jiminhome.shop/ > /dev/null
  curl -sL http://blog.jiminhome.shop/api/boards/ > /dev/null
  sleep 1
done

# Kiali Display 옵션 활성화 (UI)
# ✅ Security, Traffic Distribution, Traffic Rate, Traffic Animation
```

## Notes

- **Image Tag 업데이트**: GitHub Actions가 자동으로 업데이트
- **SelfHeal 활성화**: kubectl로 수정해도 Git 상태로 복구됨
- **Prune 활성화**: Git에서 삭제된 리소스는 클러스터에서도 삭제됨
- **Canary 배포**: Argo Rollouts가 자동으로 트래픽 가중치 조정
- **Istio mTLS**: web ↔ was 자동 암호화 (MySQL 제외)
