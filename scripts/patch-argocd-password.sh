#!/bin/bash
set -euo pipefail

echo "🔐 Patching ArgoCD admin password..."

PASSWORD="admin123"
HASH=$(htpasswd -nbBC 10 "" "$PASSWORD" | tr -d ':
' | sed 's/^\$2y/\$2a/')
kubectl -n argocd patch secret argocd-secret -p '{"stringData": {"admin.password": "'"$HASH"'", "admin.passwordMtime": "'$(date +%FT%T%Z)'"}}'

echo "✅ ArgoCD password set to 'admin123'"
