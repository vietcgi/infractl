#!/bin/bash
set -euo pipefail

echo "📦 Installing ArgoCD..."
kubectl create namespace argocd || true
kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml

echo "⏳ Waiting for ArgoCD server..."
kubectl rollout status deployment argocd-server -n argocd --timeout=180s

# 🚀 Auto-apply ArgoCD bootstrap apps
if [ -f "apps/system/bootstrap-system-apps.yaml" ]; then
  echo "🚀 Applying ArgoCD bootstrap app: apps/system/bootstrap-system-apps.yaml"
  kubectl apply -f apps/system/bootstrap-system-apps.yaml
else
  echo "⚠️  Warning: apps/system/bootstrap-system-apps.yaml not found, skipping auto-bootstrap"
fi
