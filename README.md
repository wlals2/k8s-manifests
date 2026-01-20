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
