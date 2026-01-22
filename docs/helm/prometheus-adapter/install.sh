#!/bin/bash
# Prometheus Adapter - Custom Metrics API
# Chart: prometheus-community/prometheus-adapter
# Version: 5.2.0
# Docs: https://github.com/kubernetes-sigs/prometheus-adapter

set -e

NAMESPACE="monitoring"
RELEASE="prometheus-adapter"
CHART="prometheus-community/prometheus-adapter"
VERSION="5.2.0"

# Add repo
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update

# Install or Upgrade
helm upgrade --install ${RELEASE} ${CHART} \
  --namespace ${NAMESPACE} \
  --create-namespace \
  --version ${VERSION} \
  -f values.yaml

echo "✅ Prometheus Adapter ${VERSION} installed/upgraded in ${NAMESPACE}"
echo ""
echo "📋 확인 명령어:"
echo "  kubectl get pods -n ${NAMESPACE} -l app.kubernetes.io/name=prometheus-adapter"
echo "  kubectl get --raw /apis/custom.metrics.k8s.io/v1beta1 | jq '.resources[].name'"
