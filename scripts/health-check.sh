#!/bin/bash

set -euo pipefail

LOG="/tmp/e-gitops-health.log"
: > "$LOG"

echo "🩺 e-gitops Platform Health Check" | tee -a "$LOG"

# Load Postmark config from .env
if [ -f ".env" ]; then
  export $(grep -v '^#' .env | xargs)
else
  echo "⚠️  .env file not found. Email alerts disabled." | tee -a "$LOG"
fi

function send_email() {
  if [ -z "${POSTMARK_TOKEN:-}" ] || [ -z "${POSTMARK_FROM:-}" ] || [ -z "${POSTMARK_TO:-}" ]; then
    echo "⚠️  Postmark not configured. Skipping email." >> "$LOG"
    return
  fi
  SUBJECT="$1"
  BODY=$(cat "$LOG")
  curl -s -X POST "https://api.postmarkapp.com/email"     -H "Accept: application/json"     -H "Content-Type: application/json"     -H "X-Postmark-Server-Token: $POSTMARK_TOKEN"     -d "{
      "From": "$POSTMARK_FROM",
      "To": "$POSTMARK_TO",
      "Subject": "$SUBJECT",
      "TextBody": "$BODY"
    }" >> "$LOG"
}

# Run health checks
function check() {
  echo -e "\n🔎 $1" | tee -a "$LOG"
  if ! eval "$2" >> "$LOG" 2>&1; then
    echo "❌ $1 failed" | tee -a "$LOG"
    return 1
  else
    echo "✅ $1 OK" | tee -a "$LOG"
  fi
}

FAILURES=0

check "Nodes" "kubectl get nodes -o wide" || ((FAILURES++))
check "ArgoCD pods" "kubectl get pods -n argocd" || ((FAILURES++))
check "ArgoCD applications" "kubectl get applications -n argocd" || ((FAILURES++))
check "Cert-Manager" "kubectl get pods -n cert-manager" || ((FAILURES++))
check "ClusterIssuer" "kubectl get clusterissuer" || ((FAILURES++))
check "Ingress" "kubectl get ingress -A" || ((FAILURES++))
check "Certificates" "kubectl get certificate -A" || ((FAILURES++))
check "Monitoring" "kubectl get pods -n monitoring" || ((FAILURES++))
check "SealedSecrets Controller" "kubectl get pods -n kube-system | grep sealed-secrets" || ((FAILURES++))

# Email result
if [ "$FAILURES" -eq 0 ]; then
  send_email "✅ e-gitops Health Check PASSED"
else
  send_email "❌ e-gitops Health Check FAILED ($FAILURES issue(s))"
fi

cat "$LOG"
exit $FAILURES
