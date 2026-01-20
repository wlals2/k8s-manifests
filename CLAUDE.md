# k8s-manifests 프로젝트 규칙

> Kubernetes manifest repository for ArgoCD GitOps

---

## 1. 응답 스타일 (필수)

- **Thinking은 한글로 작성**
- **모든 명령어 실행 시 반드시 설명 추가**:
  ```
  ### 🔍 [명령어]

  **왜?** - 목적
  **전/후:** - 상태 변화
  **주의:** - 위험 요소
  ```

---

## 2. 문서화 정책 (필수!)

### ⛔ 금지 사항
- ❌ **루트 디렉터리에 MD 파일 생성 절대 금지** (README.md 제외)
- ❌ 작업 중 자동으로 MD 파일 생성하지 말 것
- ❌ 사용자가 요청하지 않았는데 문서화하지 말 것

### ✅ 올바른 문서화 위치

**모든 MD 파일은 `docs/` 디렉터리 내에 작성**

```
k8s-manifests/
├── README.md                    # ✅ 루트 (GitHub 표시용, 예외)
├── docs/
│   ├── CURRENT-STATE.md         # ✅ 작업 진행 상황
│   ├── TROUBLESHOOTING.md       # ✅ 문제 해결 가이드
│   ├── ARCHITECTURE.md          # ✅ 아키텍처 문서
│   └── ...                      # ✅ 기타 모든 MD 파일
└── blog-system/
    └── *.yaml
```

### 문서 작성 순서

1. **작업 먼저 완료** (manifest 작성, 배포 등)
2. **작업 요약 제공** (텍스트로만)
3. **사용자에게 문서화 여부 확인**
4. 사용자가 "예"라고 답하면 → 그때 `docs/` 내에 MD 파일 작성

### 문서화가 필요한 경우

**오직** 사용자가 명시적으로 요청할 때만:
- "md 파일로 정리해줘"
- "문서화해줘"
- "가이드 만들어줘"
- "트러블슈팅 정리해줘"

---

## 3. ArgoCD 관리 방식

### 중요 원칙

**ArgoCD가 관리하는 리소스는 kubectl로 직접 수정하지 않음**

- ArgoCD는 selfHeal 모드 활성화
- kubectl로 수정해도 Git 상태로 자동 복구됨
- **모든 변경은 Git Push를 통해 수행**

### 변경 방법

```bash
# 1. manifest 파일 수정
vi blog-system/web-rollout.yaml

# 2. Git 커밋 및 푸시
git add blog-system/web-rollout.yaml
git commit -m "scale: web replicas 2 → 3"
git push

# 3. ArgoCD 자동 동기화 (3초 이내)
# 4. Kubernetes 자동 반영
```

### 금지 사항

- ❌ `kubectl apply -f` 직접 사용 금지 (ArgoCD 관리 리소스)
- ❌ `kubectl edit` 직접 사용 금지 (selfHeal로 되돌려짐)
- ❌ manifest 파일 없이 임시 리소스 생성 금지

---

## 4. Istio Service Mesh 규칙

### MySQL JDBC 호환성 (중요!)

**MySQL은 Istio mesh에서 제외 필수**

**이유**:
- MySQL JDBC 드라이버는 평문 TCP/IP 연결 사용
- Istio sidecar가 mTLS 협상 시도 → 연결 실패
- WAS CrashLoopBackOff 발생

**해결**:
1. `sidecar.istio.io/inject: "false"` annotation 추가
2. PeerAuthentication `mode: PERMISSIVE` 설정

### mTLS 모드

**PERMISSIVE 모드 사용** (STRICT 아님)

**이유**:
- Nginx Ingress → web pod: 평문 연결 필요
- STRICT 모드 사용 시 Ingress 접근 불가

---

## 5. Argo Rollouts + Istio 통합

### Canary 배포 전략

**web-rollout.yaml**:
- 10% → 50% → 90% → 100% (각 30초 대기)
- Istio VirtualService + DestinationRule 연동

### 배포 확인

```bash
# Rollout 상태 확인
kubectl argo rollouts get rollout web -n blog-system

# Rollout 수동 승인 (필요 시)
kubectl argo rollouts promote web -n blog-system

# Rollout 중단 (문제 발생 시)
kubectl argo rollouts abort web -n blog-system
```

---

## 6. 트러블슈팅 체크리스트

### WAS CrashLoopBackOff
1. MySQL Istio 제외 확인: `sidecar.istio.io/inject: "false"`
2. PeerAuthentication PERMISSIVE 확인
3. MySQL Service 연결 확인

### Kiali 트래픽 안 보임
1. Display 옵션 활성화 (Security, Traffic Rate)
2. 트래픽 생성 (curl 반복)
3. Ingress → web 직접 라우팅 확인 (Istio mesh 우회 여부)

### ArgoCD Sync 실패
1. YAML 문법 오류 확인
2. Namespace 존재 확인
3. ArgoCD Application 로그 확인

---

## 7. 파일 위치

| 파일 | 경로 |
|------|------|
| **Ingress** | blog-system/blog-ingress.yaml |
| **Web Rollout** | blog-system/web-rollout.yaml |
| **WAS Deployment** | blog-system/was-deployment.yaml |
| **MySQL Deployment** | blog-system/mysql-deployment.yaml |
| **Istio mTLS** | blog-system/mtls-peerauthentication.yaml |
| **Circuit Breaker** | blog-system/mysql-circuit-breaker.yaml |
| **문서** | docs/ (모든 MD 파일) |

---

## 8. 다음 작업 시 확인 사항

1. ✅ 변경 사항을 Git에 커밋했는가?
2. ✅ ArgoCD Sync 상태를 확인했는가?
3. ✅ Rollout이 정상 완료되었는가?
4. ✅ Kiali에서 트래픽 흐름을 확인했는가?
5. ✅ 문서화가 필요한가? (사용자에게 확인)

---

**작성일**: 2026-01-20
**프로젝트**: k8s-manifests (ArgoCD GitOps)
**주요 기술**: ArgoCD, Argo Rollouts, Istio Service Mesh, Kiali
