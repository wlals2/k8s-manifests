#!/bin/bash
# Longhorn - 분산 스토리지
# Chart: longhorn/longhorn
# Version: 1.10.1
# Docs: https://longhorn.io/docs/

set -e

NAMESPACE="longhorn-system"
RELEASE="longhorn"
CHART="longhorn/longhorn"
VERSION="1.10.1"

# Add repo
helm repo add longhorn https://charts.longhorn.io
helm repo update

# Install or Upgrade
helm upgrade --install ${RELEASE} ${CHART} \
  --namespace ${NAMESPACE} \
  --create-namespace \
  --version ${VERSION} \
  -f values.yaml

echo "✅ Longhorn ${VERSION} installed/upgraded in ${NAMESPACE}"
echo ""
echo "📋 확인 명령어:"
echo "  kubectl get pods -n ${NAMESPACE}"
echo "  kubectl get storageclass longhorn"
