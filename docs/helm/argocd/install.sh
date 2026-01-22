#!/bin/bash
# ArgoCD - GitOps CD
# Chart: argo/argo-cd
# Version: 9.3.4
# Docs: https://argo-cd.readthedocs.io/

set -e

NAMESPACE="argocd"
RELEASE="argocd"
CHART="argo/argo-cd"
VERSION="9.3.4"

# Add repo
helm repo add argo https://argoproj.github.io/argo-helm
helm repo update

# Install or Upgrade
helm upgrade --install ${RELEASE} ${CHART} \
  --namespace ${NAMESPACE} \
  --create-namespace \
  --version ${VERSION} \
  -f values.yaml

echo "✅ ArgoCD ${VERSION} installed/upgraded in ${NAMESPACE}"
echo ""
echo "📋 확인 명령어:"
echo "  kubectl get pods -n ${NAMESPACE}"
echo "  kubectl get svc -n ${NAMESPACE}"
echo ""
echo "📋 초기 비밀번호 확인:"
echo "  kubectl -n ${NAMESPACE} get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d"
