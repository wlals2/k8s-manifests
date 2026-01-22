#!/bin/bash
# Kube State Metrics - Kubernetes 메트릭 수집
# Chart: prometheus-community/kube-state-metrics
# Version: 7.0.1
# Docs: https://github.com/kubernetes/kube-state-metrics

set -e

NAMESPACE="monitoring"
RELEASE="kube-state-metrics"
CHART="prometheus-community/kube-state-metrics"
VERSION="7.0.1"

# Add repo
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update

# Install or Upgrade
helm upgrade --install ${RELEASE} ${CHART} \
  --namespace ${NAMESPACE} \
  --create-namespace \
  --version ${VERSION} \
  -f values.yaml

echo "✅ Kube State Metrics ${VERSION} installed/upgraded in ${NAMESPACE}"
echo ""
echo "📋 확인 명령어:"
echo "  kubectl get pods -n ${NAMESPACE} -l app.kubernetes.io/name=kube-state-metrics"
