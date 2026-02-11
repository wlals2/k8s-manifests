# Wazuh 10일 로그 보관 정책 설정

## 개요

**목적**: Wazuh Indexer에 저장된 로그를 **10일 후 자동 삭제**하여 PVC 용량 관리

**환경**:
- PVC 용량: 15Gi (Indexer, Manager Master 각각)
- 보관 기간: 10일
- 삭제 대상: `wazuh-alerts-*`, `wazuh-archives-*` 인덱스

**왜 필요한가?**:
- Wazuh Indexer는 매일 새로운 인덱스 생성 (롤오버)
- 오래된 인덱스를 삭제하지 않으면 PVC 용량 초과
- 15Gi PVC에 10일 이상 로그 저장 시 용량 부족

---

## 설정 방법

### 1단계: Wazuh Indexer API 접근 테스트

```bash
# Indexer Pod 이름 확인
kubectl get pods -n security -l app=wazuh-indexer

# API 접근 테스트 (health check)
kubectl exec -n security wazuh-indexer-0 -- \
  curl -s -u admin:SecretPassword \
  http://localhost:9200/_cluster/health | jq
```

**예상 출력**:
```json
{
  "cluster_name": "wazuh",
  "status": "green",
  "number_of_nodes": 1
}
```

---

### 2단계: 현재 ILM 정책 확인

```bash
# 모든 ILM 정책 조회
kubectl exec -n security wazuh-indexer-0 -- \
  curl -s -u admin:SecretPassword \
  http://localhost:9200/_ilm/policy | jq
```

**예상 출력**:
- 기본 정책이 없거나, `wazuh-alerts-policy` 등이 존재할 수 있음

---

### 3단계: 10일 보관 ILM 정책 생성

#### (A) Alerts 인덱스 정책 (wazuh-alerts-*)

```bash
kubectl exec -n security wazuh-indexer-0 -- \
  curl -X PUT -s -u admin:SecretPassword \
  -H 'Content-Type: application/json' \
  http://localhost:9200/_ilm/policy/wazuh-alerts-policy -d '{
    "policy": {
      "phases": {
        "hot": {
          "actions": {
            "rollover": {
              "max_age": "1d",
              "max_size": "5gb"
            }
          }
        },
        "delete": {
          "min_age": "10d",
          "actions": {
            "delete": {}
          }
        }
      }
    }
  }'
```

**설명**:
- **hot phase**: 1일마다 또는 5GB마다 새 인덱스 생성 (롤오버)
- **delete phase**: 10일 후 인덱스 삭제

#### (B) Archives 인덱스 정책 (wazuh-archives-*)

```bash
kubectl exec -n security wazuh-indexer-0 -- \
  curl -X PUT -s -u admin:SecretPassword \
  -H 'Content-Type: application/json' \
  http://localhost:9200/_ilm/policy/wazuh-archives-policy -d '{
    "policy": {
      "phases": {
        "hot": {
          "actions": {
            "rollover": {
              "max_age": "1d",
              "max_size": "10gb"
            }
          }
        },
        "delete": {
          "min_age": "10d",
          "actions": {
            "delete": {}
          }
        }
      }
    }
  }'
```

---

### 4단계: 인덱스 템플릿에 ILM 정책 적용

#### (A) Alerts 인덱스 템플릿

```bash
kubectl exec -n security wazuh-indexer-0 -- \
  curl -X PUT -s -u admin:SecretPassword \
  -H 'Content-Type: application/json' \
  http://localhost:9200/_index_template/wazuh-alerts -d '{
    "index_patterns": ["wazuh-alerts-*"],
    "template": {
      "settings": {
        "index.lifecycle.name": "wazuh-alerts-policy",
        "index.lifecycle.rollover_alias": "wazuh-alerts"
      }
    }
  }'
```

#### (B) Archives 인덱스 템플릿

```bash
kubectl exec -n security wazuh-indexer-0 -- \
  curl -X PUT -s -u admin:SecretPassword \
  -H 'Content-Type: application/json' \
  http://localhost:9200/_index_template/wazuh-archives -d '{
    "index_patterns": ["wazuh-archives-*"],
    "template": {
      "settings": {
        "index.lifecycle.name": "wazuh-archives-policy",
        "index.lifecycle.rollover_alias": "wazuh-archives"
      }
    }
  }'
```

---

### 5단계: 검증

#### (A) ILM 정책 확인

```bash
# Alerts 정책 확인
kubectl exec -n security wazuh-indexer-0 -- \
  curl -s -u admin:SecretPassword \
  http://localhost:9200/_ilm/policy/wazuh-alerts-policy | jq

# Archives 정책 확인
kubectl exec -n security wazuh-indexer-0 -- \
  curl -s -u admin:SecretPassword \
  http://localhost:9200/_ilm/policy/wazuh-archives-policy | jq
```

#### (B) 인덱스 확인

```bash
# 모든 인덱스 조회 (생성 날짜 확인)
kubectl exec -n security wazuh-indexer-0 -- \
  curl -s -u admin:SecretPassword \
  http://localhost:9200/_cat/indices/wazuh-*?v
```

**예상 출력**:
```
health status index                   pri rep docs.count store.size
yellow open   wazuh-alerts-2026.02.11   1   1        120     256kb
```

#### (C) ILM 정책 적용 확인

```bash
# 특정 인덱스의 ILM 설정 확인
kubectl exec -n security wazuh-indexer-0 -- \
  curl -s -u admin:SecretPassword \
  http://localhost:9200/wazuh-alerts-*/_ilm/explain | jq
```

**예상 출력**:
```json
{
  "indices": {
    "wazuh-alerts-2026.02.11": {
      "policy": "wazuh-alerts-policy",
      "phase": "hot",
      "age": "1h"
    }
  }
}
```

---

## 주의사항

### 1. 기존 인덱스에는 적용 안 됨

ILM 정책은 **새로 생성되는 인덱스**에만 적용됩니다.

**기존 인덱스 수동 삭제**:
```bash
# 10일 이전 인덱스 확인
kubectl exec -n security wazuh-indexer-0 -- \
  curl -s -u admin:SecretPassword \
  http://localhost:9200/_cat/indices/wazuh-*?v

# 수동 삭제 (예: 2026.02.01 인덱스)
kubectl exec -n security wazuh-indexer-0 -- \
  curl -X DELETE -s -u admin:SecretPassword \
  http://localhost:9200/wazuh-alerts-2026.02.01
```

### 2. PVC 용량 모니터링

ILM 정책이 작동해도 **로그 증가율이 높으면** PVC 용량 부족 가능

**모니터링 방법**:
```bash
# Indexer Pod 디스크 사용량 확인
kubectl exec -n security wazuh-indexer-0 -- df -h /usr/share/wazuh-indexer/data
```

**Prometheus 메트릭** (향후 구현):
- `kubelet_volume_stats_used_bytes{persistentvolumeclaim="wazuh-indexer-wazuh-indexer-0"}`

### 3. Rollover Alias 필요

ILM 정책이 작동하려면 **Rollover Alias**가 설정되어 있어야 합니다.

**확인 방법**:
```bash
kubectl exec -n security wazuh-indexer-0 -- \
  curl -s -u admin:SecretPassword \
  http://localhost:9200/_alias/wazuh-alerts | jq
```

**없으면 생성**:
```bash
kubectl exec -n security wazuh-indexer-0 -- \
  curl -X POST -s -u admin:SecretPassword \
  -H 'Content-Type: application/json' \
  http://localhost:9200/wazuh-alerts-000001 -d '{
    "aliases": {
      "wazuh-alerts": {
        "is_write_index": true
      }
    }
  }'
```

---

## 트러블슈팅

### 문제 1: ILM 정책이 작동하지 않음

**증상**: 10일 이전 인덱스가 삭제되지 않음

**원인**:
1. ILM Pollster가 비활성화됨
2. 인덱스에 ILM 정책이 연결되지 않음

**해결**:
```bash
# ILM Pollster 상태 확인
kubectl exec -n security wazuh-indexer-0 -- \
  curl -s -u admin:SecretPassword \
  http://localhost:9200/_ilm/status | jq

# 비활성화 시 활성화
kubectl exec -n security wazuh-indexer-0 -- \
  curl -X POST -s -u admin:SecretPassword \
  http://localhost:9200/_ilm/start
```

### 문제 2: PVC 용량 부족 경고

**증상**: `kubectl describe pvc` 시 용량 부족 경고

**해결**:
1. **즉시 조치**: 오래된 인덱스 수동 삭제
2. **근본 원인**: 로그 수집 범위 축소 또는 PVC 용량 증설 검토

```bash
# 오래된 인덱스 삭제
kubectl exec -n security wazuh-indexer-0 -- \
  curl -X DELETE -s -u admin:SecretPassword \
  'http://localhost:9200/wazuh-alerts-*' -d '{
    "query": {
      "range": {
        "@timestamp": {
          "lt": "now-10d"
        }
      }
    }
  }'
```

---

## 자동화 (ConfigMap + initContainer)

**향후 개선 방안**: Helm Chart에 ILM 정책 자동 적용 initContainer 추가

```yaml
# values.yaml
wazuh:
  indexer:
    ilm:
      enabled: true
      retention_days: 10
      rollover_size: "5gb"
```

---

## 참고 자료

- Wazuh Indexer: https://documentation.wazuh.com/current/user-manual/elasticsearch/
- Elasticsearch ILM: https://www.elastic.co/guide/en/elasticsearch/reference/current/index-lifecycle-management.html
- Rollover API: https://www.elastic.co/guide/en/elasticsearch/reference/current/indices-rollover-index.html

---

**작성일**: 2026-02-11
**작성자**: Claude (AI Assistant)
**검증 상태**: 미검증 (사용자가 직접 테스트 필요)
