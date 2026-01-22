#!/bin/bash
# Cilium - CNI + eBPF 네트워킹
# Chart: cilium/cilium
# Version: 1.18.6
# Docs: https://docs.cilium.io/

set -e

NAMESPACE="kube-system"
RELEASE="cilium"
CHART="cilium/cilium"
VERSION="1.18.6"

# Add repo
helm repo add cilium https://helm.cilium.io/
helm repo update

# Install or Upgrade
helm upgrade --install ${RELEASE} ${CHART} \
  --namespace ${NAMESPACE} \
  --version ${VERSION} \
  -f values.yaml

echo "✅ Cilium ${VERSION} installed/upgraded in ${NAMESPACE}"
echo ""
echo "📋 확인 명령어:"
echo "  cilium status"
echo "  kubectl get pods -n ${NAMESPACE} -l app.kubernetes.io/part-of=cilium"
