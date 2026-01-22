# Helm Releases 관리

> ArgoCD 외부에서 Helm으로 직접 관리하는 서비스들
>
> **관리 원칙**: Chart는 공식 repo에서, 오버라이드 값만 Git에서 관리

**최종 업데이트:** 2026-01-22

---

## 서비스 목록

| 서비스 | Namespace | Chart Version | 관리 주체 | 용도 |
|--------|-----------|---------------|-----------|------|
| **longhorn** | longhorn-system | 1.10.1 | Helm | 분산 스토리지 (PV) |
| **cilium** | kube-system | 1.18.6 | Helm | CNI + eBPF 네트워킹 |
| **loki-stack** | monitoring | 2.10.3 | Helm | 로그 수집/저장 |
| **prometheus-adapter** | monitoring | 5.2.0 | Helm | Custom Metrics API |
| **vpa** | kube-system | 4.10.1 | Helm | Vertical Pod Autoscaler |
| **kube-state-metrics** | monitoring | 7.0.1 | Helm | K8s 메트릭 수집 |
| **argocd** | argocd | 9.3.4 | Helm | GitOps CD |

---

## 관리 방식 비교

```
┌─────────────────────────────────────────────────────────────┐
│                    클러스터 관리 구조                        │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────────┐         ┌─────────────────┐           │
│  │   ArgoCD 관리    │         │   Helm 직접 관리  │           │
│  │   (GitOps)      │         │   (수동)         │           │
│  ├─────────────────┤         ├─────────────────┤           │
│  │ • blog-system   │         │ • longhorn      │           │
│  │ • monitoring/*  │         │ • cilium        │           │
│  │                 │         │ • loki-stack    │           │
│  │                 │         │ • prometheus-   │           │
│  │                 │         │   adapter       │           │
│  │                 │         │ • vpa           │           │
│  │                 │         │ • kube-state-   │           │
│  │                 │         │   metrics       │           │
│  │                 │         │ • argocd        │           │
│  └─────────────────┘         └─────────────────┘           │
│         │                           │                      │
│         ▼                           ▼                      │
│  k8s-manifests/              docs/helm/                    │
│  (자동 Sync)                 (수동 helm upgrade)            │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 설치 순서 (클러스터 초기 구축 시)

```bash
# 1. CNI (네트워크) - 가장 먼저
cd docs/helm/cilium && ./install.sh

# 2. 스토리지
cd docs/helm/longhorn && ./install.sh

# 3. GitOps
cd docs/helm/argocd && ./install.sh

# 4. 모니터링
cd docs/helm/kube-state-metrics && ./install.sh
cd docs/helm/loki-stack && ./install.sh
cd docs/helm/prometheus-adapter && ./install.sh

# 5. 오토스케일링
cd docs/helm/vpa && ./install.sh
```

---

## 업그레이드 방법

```bash
# 1. values.yaml 수정
vi docs/helm/longhorn/values.yaml

# 2. helm upgrade 실행
cd docs/helm/longhorn && ./install.sh

# 3. 변경사항 Git 커밋
git add docs/helm/longhorn/values.yaml
git commit -m "chore: Update longhorn values"
git push
```

---

## 주의사항

1. **values.yaml 수정 후 반드시 Git 커밋** - 변경 이력 추적
2. **Chart 버전 변경 시 install.sh도 수정** - 버전 일치 유지
3. **업그레이드 전 백업** - `helm get values <release> -n <ns> --all > backup.yaml`

---

## 폴더 구조

```
docs/helm/
├── README.md              # 이 파일
├── longhorn/
│   ├── install.sh         # 설치/업그레이드 명령어
│   └── values.yaml        # 오버라이드 값
├── cilium/
│   ├── install.sh
│   └── values.yaml
├── loki-stack/
│   ├── install.sh
│   └── values.yaml
├── prometheus-adapter/
│   ├── install.sh
│   └── values.yaml
├── vpa/
│   ├── install.sh
│   └── values.yaml
├── kube-state-metrics/
│   ├── install.sh
│   └── values.yaml
└── argocd/
    ├── install.sh
    └── values.yaml
```
