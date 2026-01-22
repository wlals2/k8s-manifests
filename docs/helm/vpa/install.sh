#!/bin/bash
# VPA - Vertical Pod Autoscaler
# Chart: fairwinds-stable/vpa
# Version: 4.10.1
# Docs: https://github.com/kubernetes/autoscaler/tree/master/vertical-pod-autoscaler

set -e

NAMESPACE="kube-system"
RELEASE="vpa"
CHART="fairwinds-stable/vpa"
VERSION="4.10.1"

# Add repo
helm repo add fairwinds-stable https://charts.fairwinds.com/stable
helm repo update

# Install or Upgrade
helm upgrade --install ${RELEASE} ${CHART} \
  --namespace ${NAMESPACE} \
  --version ${VERSION} \
  -f values.yaml

echo "✅ VPA ${VERSION} installed/upgraded in ${NAMESPACE}"
echo ""
echo "📋 확인 명령어:"
echo "  kubectl get pods -n ${NAMESPACE} -l app.kubernetes.io/name=vpa"
echo "  kubectl get vpa -A"
