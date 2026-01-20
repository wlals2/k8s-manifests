# 현재 시스템 상태 및 문제 분석

**작성일**: 2026-01-20
**목적**: Istio Mesh 완전 활용을 위한 WAS API 경로 파악 및 nginx 프록시 설정

---

## 1. 현재 구조

### 기존 구조 (작동함)
```
[외부] → [Nginx Ingress 192.168.1.61]
           ├─ / → web-service:80 (Hugo)
           ├─ /board → web-service:80 (Hugo)
           └─ /api → was-service:8080 (Spring Boot) ⚠️ Istio mesh 우회
```

### 목표 구조 (Istio mesh 활용)
```
[외부] → [Nginx Ingress]
           └─ / (all paths) → web-service:80
                                ↓
                           [web pod nginx]
                                ├─ / → 정적 파일
                                └─ /api → was-service:8080 (Istio mesh 통과 🔒)
                                           ↓ mTLS
                                      [was pod]
                                           ↓
                                      [mysql]
```

**장점**:
- ✅ web → was 트래픽이 Istio mesh 통과
- ✅ mTLS 암호화 적용
- ✅ Circuit Breaking, Retry, Timeout 정책 적용
- ✅ Kiali에서 전체 서비스 메시 시각화 가능

**문제점**:
- ❌ WAS의 실제 API 경로를 정확히 파악하지 못함
- ❌ nginx 프록시 설정이 404 에러 발생

---

## 2. WAS 정보

### 이미지
```
ghcr.io/wlals2/board-was:v1
```

### 소스 코드 위치
```
/home/jimin/CICD/sourece-repo/was/
```

**주의**: 소스 코드는 PetClinic 기반이지만, 실제 배포된 이미지는 `board-was`

### 알려진 엔드포인트
- ❌ `/api/actuator/health` → 404
- ❌ `/api/boards` → 404
- ❓ `/actuator/health` → 미확인
- ❓ `/boards` → 미확인

---

## 3. 시도한 nginx 프록시 설정

### 설정 1 (실패)
```nginx
location /api/ {
    proxy_pass http://was-service:8080/api/;
}
```
**결과**: 426 Upgrade Required

### 설정 2 (실패)
```nginx
location /api {
    proxy_pass http://was-service:8080;
}
```
**결과**: 426 Upgrade Required

### 설정 3 (실패)
```nginx
location /api {
    proxy_pass http://was-service:8080;
    proxy_http_version 1.1;
    proxy_set_header Connection "";
}
```
**결과**: 404 Not Found

---

## 4. 필요한 조사

### ✅ 완료
1. WAS 이미지 확인: `ghcr.io/wlals2/board-was:v1`
2. WAS ConfigMap 확인: MySQL 연결 정보만 있음
3. WAS pod 상태: 정상 실행 중 (`actuator/health` 응답 확인)

### ⏳ 진행 필요
1. **WAS의 실제 API 경로 확인**
   ```bash
   # WAS pod에서 직접 테스트 필요
   kubectl exec -n blog-system deploy/was -c spring-boot -- sh
   # 내부에서: wget http://localhost:8080/... 테스트
   ```

2. **WAS 애플리케이션 코드 분석**
   ```bash
   # Controller 파일 확인
   find /home/jimin/CICD/sourece-repo -name "*Controller*.java"
   # @RequestMapping 어노테이션 확인
   ```

3. **WAS 시작 로그에서 매핑된 경로 확인**
   ```bash
   kubectl logs -n blog-system -l app=was -c spring-boot --tail=500 | grep "Mapped"
   ```

---

## 5. 다음 단계

### Step 1: WAS API 경로 파악
```bash
# 1. WAS pod 내부에서 직접 HTTP 요청
kubectl exec -n blog-system deploy/was -c spring-boot -- sh

# 2. 가능한 경로 테스트
wget -O- http://localhost:8080/actuator/health
wget -O- http://localhost:8080/boards
wget -O- http://localhost:8080/api/boards
wget -O- http://localhost:8080/api/actuator/health

# 3. 응답하는 경로 기록
```

### Step 2: nginx 프록시 설정 수정
```yaml
# WAS 실제 경로가 /boards라면:
location /api {
    proxy_pass http://was-service:8080;  # /api/boards → /boards
    proxy_http_version 1.1;
    proxy_set_header Connection "";
}

# WAS 실제 경로가 /api/boards라면:
location /api/ {
    proxy_pass http://was-service:8080/api/;  # /api/boards → /api/boards
    proxy_http_version 1.1;
    proxy_set_header Connection "";
}
```

### Step 3: 테스트 및 검증
```bash
# 1. nginx 프록시 설정 적용
git add blog-system/web-nginx-config.yaml
git commit -m "fix: Correct WAS API proxy path"
git push

# 2. Rollout 재시작
kubectl argo rollouts restart web -n blog-system

# 3. 테스트
curl -sL http://blog.jiminhome.shop/api/boards
```

### Step 4: Kiali 확인
```bash
# 트래픽 생성
for i in {1..50}; do
  curl -s http://blog.jiminhome.shop/ > /dev/null
  curl -sL http://blog.jiminhome.shop/api/boards > /dev/null
  sleep 1
done

# Kiali에서 확인
# http://kiali.jiminhome.shop
# web → was → mysql 연결 확인
```

---

## 6. 임시 복구 방법 (현재 상태)

Istio mesh 우회하는 기존 방식으로 복구:

```yaml
# blog-ingress.yaml
spec:
  rules:
  - host: blog.jiminhome.shop
    http:
      paths:
      - path: /api
        pathType: Prefix
        backend:
          service:
            name: was-service  # 직접 호출
            port:
              number: 8080
```

**적용**:
```bash
kubectl apply -f blog-system/blog-ingress.yaml
```

**장점**: 즉시 작동
**단점**: Istio mesh 시각화 불가 (web → was 연결 없음)

---

## 7. 파일 위치

| 파일 | 경로 |
|------|------|
| **Ingress** | /home/jimin/k8s-manifests/blog-system/blog-ingress.yaml |
| **Nginx Config** | /home/jimin/k8s-manifests/blog-system/web-nginx-config.yaml |
| **Web Rollout** | /home/jimin/k8s-manifests/blog-system/web-rollout.yaml |
| **WAS 소스** | /home/jimin/CICD/sourece-repo/was/ |
| **README** | /home/jimin/k8s-manifests/README.md |

---

## 8. 핵심 교훈

**문제**:
- WAS API 경로를 정확히 파악하지 않고 nginx 프록시 설정을 시도
- 결과: 404 에러 발생, 시간 낭비

**올바른 순서**:
1. ✅ **먼저 조사**: WAS의 실제 API 경로 파악
2. ✅ **설정 작성**: 파악한 경로 기반으로 nginx 프록시 설정
3. ✅ **테스트**: 소규모 테스트 후 전체 적용
4. ✅ **문서화**: 경로 정보를 문서화하여 이후 문제 방지

**다음에는**:
- 시스템 변경 전에 현재 상태를 먼저 문서화
- 변경할 대상의 정확한 스펙을 먼저 파악
- 단계별로 검증하며 진행

---

**다음 작업**: WAS pod에 접속하여 실제 API 경로 확인
