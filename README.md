# k8s-manifests

> Kubernetes manifest repository for ArgoCD GitOps

## Structure

```
blog-system/
├── web-deployment.yaml      # Hugo 블로그 (nginx)
├── web-service.yaml
├── was-deployment.yaml      # Spring Boot WAS
├── was-service.yaml
├── was-configmap.yaml
├── mysql-deployment.yaml    # MySQL 8.0
├── mysql-service.yaml
├── mysql-pvc.yaml           # PersistentVolumeClaim (Longhorn)
└── blog-ingress.yaml        # Ingress (blog.jiminhome.shop)
```

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

**예시:**
```bash
# replicas 변경
vi blog-system/web-deployment.yaml
# replicas: 2 → 3

git add blog-system/web-deployment.yaml
git commit -m "scale: web replicas 2 → 3"
git push

# ArgoCD 자동 동기화 확인
kubectl get pods -n blog-system
# web-xxx-1, web-xxx-2, web-xxx-3 (3개로 증가)
```

## Notes

- **Image Tag 업데이트**: GitHub Actions가 자동으로 업데이트
- **SelfHeal 활성화**: kubectl로 수정해도 Git 상태로 복구됨
- **Prune 활성화**: Git에서 삭제된 리소스는 클러스터에서도 삭제됨
