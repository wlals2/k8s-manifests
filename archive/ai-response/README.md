# AI Response Service

**AI-driven Security Incident Auto-Response System**

Falco 런타임 보안 Alert를 Claude API로 분석하여 자동으로 대응하는 시스템입니다.

---

## 🎯 개요

### 목적
- Falco가 탐지한 보안 이벤트를 AI가 분석하여 **실제 공격 여부** 판단
- False Positive 필터링 (정상 kubectl exec vs 악의적 shell 실행)
- 자동 대응: Pod 격리 (NetworkPolicy), Pod 삭제, IP 차단

### 아키텍처

```
Falco (eBPF) → Falco Sidekick → AI Response Service (FastAPI)
                                      ↓
                                Claude API (Analysis)
                                      ↓
                              Kubernetes API (Response)
                                      ↓
                              NetworkPolicy / Pod Delete
```

---

## 📂 프로젝트 구조

```
k8s-manifests/services/ai-response/
├── app/
│   ├── main.py              # FastAPI 서버
│   ├── models.py            # Pydantic 데이터 모델
│   ├── ai_engine.py         # Claude API 통합
│   ├── k8s_client.py        # Kubernetes Client
│   └── config.py            # 설정
├── Dockerfile               # 컨테이너 이미지
├── requirements.txt         # Python 의존성
├── k8s/
│   ├── deployment.yaml      # Kubernetes Deployment
│   ├── service.yaml         # Kubernetes Service
│   ├── serviceaccount.yaml  # ServiceAccount
│   ├── role.yaml            # ClusterRole (RBAC)
│   ├── rolebinding.yaml     # ClusterRoleBinding
│   └── kustomization.yml    # Kustomize
└── README.md                # 이 파일
```

---

## 🚀 설치 방법

### 1. Claude API Key 발급

Anthropic Console에서 API Key 발급:
- https://console.anthropic.com/settings/keys
- API Key 복사 (sk-ant-api03-...)

### 2. Secret 생성

```bash
# 평문 Secret 생성
kubectl create secret generic claude-api-key \
  --from-literal=api-key=sk-ant-api03-YOUR-KEY-HERE \
  -n security \
  --dry-run=client -o yaml > claude-api-key.yaml

# SealedSecret 변환
kubeseal --format yaml < claude-api-key.yaml > claude-api-key-sealed.yaml

# Git에 추가 (평문 Secret은 .gitignore에 있음)
git add claude-api-key-sealed.yaml
git commit -m "feat(security): Add Claude API key SealedSecret"
git push

# 평문 Secret 삭제
rm claude-api-key.yaml
```

### 3. Docker 이미지 빌드

```bash
# 이미지 빌드
cd /home/jimin/k8s-manifests/services/ai-response
docker build -t ai-response:latest .

# (옵션) Registry push
# docker tag ai-response:latest <registry>/ai-response:latest
# docker push <registry>/ai-response:latest
```

**Note**: 현재는 로컬 이미지 사용, 프로덕션에서는 Registry 사용 권장

### 4. Git Commit & Push

```bash
cd /home/jimin/k8s-manifests
git add services/ai-response/
git add argocd/ai-response-app.yaml
git add apps/falco/values.yaml
git commit -m "feat(security): Add AI auto-response system (SOAR framework)"
git push
```

### 5. ArgoCD 자동 배포

```bash
# root-app이 자동으로 ai-response-app.yaml 감지 (3-5초)
kubectl get applications -n argocd

# ai-response Application 생성 확인
kubectl get application ai-response -n argocd

# 배포 확인
kubectl get pods -n security
kubectl get svc -n security
kubectl logs -n security ai-response-service-xxx
```

---

## 🧪 테스트

### 1. Service 상태 확인

```bash
# Pod 상태
kubectl get pods -n security -l app=ai-response

# 로그 확인
kubectl logs -n security -l app=ai-response -f

# Health check
kubectl exec -n security deploy/ai-response-service -- \
  curl http://localhost:8000/health
```

### 2. Falco Alert 수신 테스트

```bash
# Test Pod 생성
kubectl run attack-pod --image=nginx --restart=Never

# Shell 실행 (Falco가 탐지)
kubectl exec -it attack-pod -- /bin/bash

# 예상 결과:
# 1. Falco Alert 발생 (5초 이내)
# 2. AI Service 로그: "Received Falco alert: Terminal shell in container"
# 3. Claude API 분석: "Risk Score: 75, Action: isolate"
# 4. NetworkPolicy 생성 (Dry-run 모드에서는 로그만)
```

### 3. Dry-run 모드 확인

```bash
# Deployment의 DRY_RUN 환경 변수 확인
kubectl get deploy ai-response-service -n security -o yaml | grep DRY_RUN

# DRY_RUN=true: AI 분석만 수행, 실제 대응 없음
# DRY_RUN=false: 실제 자동 대응 수행 (Phase 2 이후)
```

---

## 📊 운영 모드

### Phase 1: Dry-run 모드 (현재)

```yaml
env:
  - name: DRY_RUN
    value: "true"
```

**동작**:
- AI가 Alert 분석
- Risk Score 및 Action 로깅
- 실제 대응 없음 (NetworkPolicy 생성 안 함)

**목적**: AI 판단 정확도 검증, False Positive 튜닝

### Phase 2: 격리만 활성화 (1주일 후)

```yaml
env:
  - name: DRY_RUN
    value: "false"
  - name: RISK_THRESHOLD_DELETE
    value: "999"  # Pod 삭제 비활성화
```

**동작**:
- NetworkPolicy 생성 (Pod 격리)
- Pod 삭제는 비활성화

### Phase 3: 전체 활성화 (2주일 후)

```yaml
env:
  - name: DRY_RUN
    value: "false"
  - name: RISK_THRESHOLD_DELETE
    value: "80"
```

**동작**:
- 모든 자동 대응 활성화
- 24/7 자동 보안 운영

---

## 🔧 설정

### 환경 변수

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `CLAUDE_API_KEY` | (필수) | Claude API Key |
| `DRY_RUN` | `true` | Dry-run 모드 |
| `LOG_LEVEL` | `INFO` | 로그 레벨 |
| `RISK_THRESHOLD_ISOLATE` | `50` | 격리 임계값 |
| `RISK_THRESHOLD_DELETE` | `80` | 삭제 임계값 |
| `K8S_IN_CLUSTER` | `true` | InClusterConfig 사용 |

### Risk Score 임계값

| Score | Action | 설명 |
|-------|--------|------|
| 0-49 | monitor | 로그만 기록 |
| 50-79 | isolate | NetworkPolicy 생성 |
| 80-94 | delete | Pod 삭제 |
| 95-100 | block | IP 차단 (미구현) |

---

## 🐞 트러블슈팅

### 1. Pod가 시작되지 않음

```bash
# Pod 상태 확인
kubectl describe pod -n security -l app=ai-response

# 일반적인 원인:
# - Secret이 없음 (claude-api-key)
# - 이미지가 없음 (ImagePullBackOff)
```

**해결**:
```bash
# Secret 확인
kubectl get secret -n security claude-api-key

# 이미지 확인
kubectl get events -n security --field-selector involvedObject.kind=Pod
```

### 2. Falco Alert가 AI Service에 도달하지 않음

```bash
# Falco Sidekick 로그 확인
kubectl logs -n falco -l app.kubernetes.io/name=falcosidekick -f

# customhooks 설정 확인
kubectl get cm -n falco falco-falcosidekick -o yaml | grep customhooks
```

**해결**:
- Falco values.yaml의 customhooks 설정 확인
- Service DNS 확인: `ai-response-service.security.svc.cluster.local`

### 3. Claude API 호출 실패

```bash
# AI Service 로그 확인
kubectl logs -n security -l app=ai-response | grep "Claude API error"

# API Key 확인
kubectl get secret claude-api-key -n security -o jsonpath='{.data.api-key}' | base64 -d
```

**해결**:
- API Key 만료 확인
- API Rate Limit 확인
- 네트워크 연결 확인

---

## 📈 모니터링

### 로그 확인

```bash
# 실시간 로그
kubectl logs -n security -l app=ai-response -f

# 특정 Alert 검색
kubectl logs -n security -l app=ai-response | grep "Terminal shell"
```

### Prometheus Metrics (미구현)

```promql
# 향후 추가 예정
ai_response_alerts_total
ai_response_risk_score_distribution
ai_response_actions_total{action="isolate"}
```

---

## 🔐 보안

### RBAC

AI Response Service는 최소 권한 원칙을 따릅니다:

```yaml
ClusterRole:
  - NetworkPolicy: get, list, create, delete
  - Pod: get, list, delete
  - CiliumNetworkPolicy: get, list, create, delete
```

**허용되지 않는 작업**:
- Deployment 수정
- ConfigMap/Secret 조회
- Node 접근

### API Key 보안

- SealedSecret로 암호화 저장
- 환경 변수로 주입 (평문 노출 방지)
- Secret 파일은 `.gitignore`에 추가

---

## 📚 참고 자료

- [Falco Documentation](https://falco.org/docs/)
- [Anthropic Claude API](https://docs.anthropic.com/)
- [Kubernetes Client Python](https://github.com/kubernetes-client/python)

---

## 🎓 학습 노트

이 프로젝트는 다음 개념을 학습하기 위해 구축되었습니다:

1. **SOAR (Security Orchestration, Automation and Response)**
2. **AI-driven Security Operations**
3. **Kubernetes RBAC (Role-Based Access Control)**
4. **Falco Runtime Security**
5. **GitOps with ArgoCD**

---

**Author**: Jimin (2026-02-15)
**Version**: 1.0.0
