#!/bin/bash
# Loki Stack - 로그 수집/저장
# Chart: grafana/loki-stack
# Version: 2.10.3
# Docs: https://grafana.com/docs/loki/

set -e

NAMESPACE="monitoring"
RELEASE="loki-stack"
CHART="grafana/loki-stack"
VERSION="2.10.3"

# Add repo
helm repo add grafana https://grafana.github.io/helm-charts
helm repo update

# Install or Upgrade
helm upgrade --install ${RELEASE} ${CHART} \
  --namespace ${NAMESPACE} \
  --create-namespace \
  --version ${VERSION} \
  -f values.yaml

echo "✅ Loki Stack ${VERSION} installed/upgraded in ${NAMESPACE}"
echo ""
echo "📋 확인 명령어:"
echo "  kubectl get pods -n ${NAMESPACE} -l app=loki"
echo "  kubectl get pods -n ${NAMESPACE} -l app=promtail"
