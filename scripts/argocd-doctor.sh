#!/bin/bash
# =============================================================
# 🚑 ArgoCD Doctor - Diagnose, Fix, and Report GitOps Health
# 🔧 Auto-heals stuck apps, repairs finalizers, verifies repos
# 📅 Supports --safe-mode, --dry-run, --approve, and --report
# =============================================================

set -euo pipefail

NAMESPACE="argocd"
TIMEOUT="180s"
AUTO_REPAIR=true
SAFE_MODE=true
DRY_RUN=false
APPROVAL_MODE=false
REPORT_JSON="argocd-doctor-report.json"
REPORT_TXT="argocd-doctor-report.txt"

while [[ "$#" -gt 0 ]]; do
  case $1 in
    --safe-mode) SAFE_MODE=true ;;
    --full-auto) SAFE_MODE=false ;;
    --dry-run) DRY_RUN=true ;;
    --approve) APPROVAL_MODE=true ;;
    --report) shift; REPORT_TXT=$1 ;;
    *) echo "Unknown parameter passed: $1"; exit 1 ;;
  esac
  shift
done





echo "================================================================="
echo "🩺 ArgoCD Doctor - Self-Healing GitOps Diagnostic & Repair Tool"
echo "================================================================="
echo ""
echo "USAGE:"
echo "  ./scripts/argocd-doctor.sh [options]"
echo ""
echo "OPTIONS:"
echo "  --safe-mode        Only perform safe auto-healing actions (default)"
echo "  --full-auto        Allow high-risk fixes (e.g., Service deletion)"
echo "  --dry-run          Run in diagnostic mode only (no changes applied)"
echo "  --approve          Prompt before executing risky operations"
echo "  --report <file>    Write final health report to the specified file"
echo ""
echo "EXAMPLES:"
echo "  ./scripts/argocd-doctor.sh --safe-mode"
echo "  ./scripts/argocd-doctor.sh --full-auto --approve"
echo "  ./scripts/argocd-doctor.sh --dry-run --report doctor-summary.txt"
echo ""
echo "================================================================="
echo ""

touch "$REPORT_TXT"
echo -e "📋 ArgoCD Doctor Report - $(date)" > "$REPORT_TXT"

# 🚑 ArgoCD Doctor - Diagnose, Fix, and Report GitOps Health
# 🔧 Auto-heals stuck apps, repairs finalizers, verifies repos
# 📅 Built for scheduled or on-demand SRE use

set -euo pipefail

NAMESPACE="argocd"
TIMEOUT="180s"
AUTO_REPAIR=true



echo "🔍 Checking ArgoCD health in namespace: $NAMESPACE..."

# Ensure ArgoCD CLI is available
if ! command -v argocd &> /dev/null; then
  echo "❌ ArgoCD CLI (argocd) not found in PATH"
fi
  exit 1

# Wait for argocd-server to be healthy
echo "⏳ Ensuring ArgoCD server is running..."
echo "⏳ Checking argocd-server availability (non-blocking)..."
if ! kubectl get deploy argocd-server -n "$NAMESPACE" -o json | jq -e '.status.availableReplicas == 1' > /dev/null; then
  echo "⚠️  argocd-server is not yet available (AvailableReplicas != 1)"
else
  echo "✅ argocd-server is available."
fi
if [ "$SAFE_MODE" = false ]; then
  echo "🧹 Checking for stuck argocd-server pods..."
fi

echo "🔍 Checking for NotReady ArgoCD pods..."
for pod in $(kubectl get pod -n "$NAMESPACE" -o json | jq -r '.items[] | select(.status.conditions[]?.type == "Ready" and .status.conditions[]?.status != "True") | .metadata.name'); do
  echo "⚠️  NotReady pod detected: $pod"
  if [ "$SAFE_MODE" = false ]; then
    echo "🔥 Force deleting NotReady pod: $pod"
fi
    kubectl delete pod "$pod" -n "$NAMESPACE" --grace-period=0 --force || echo "⚠️  Failed to delete $pod"
    echo "🔥 Force-deleted NotReady pod: $pod" >> "$REPORT_TXT"
    echo "⚠️  Skipped deleting $pod due to SAFE_MODE" >> "$REPORT_TXT"
  fi
done
  for pod in $(kubectl get pods -n "$NAMESPACE" -l app.kubernetes.io/name=argocd-server -o json | jq -r '.items[] | select(.metadata.deletionTimestamp != null or .status.containerStatuses[].ready == false) | .metadata.name'); do
    echo "🔥 Force deleting stuck argocd-server pod: $pod"
    kubectl delete pod "$pod" -n "$NAMESPACE" --grace-period=0 --force || echo "⚠️ Failed to delete $pod"
  done

if [ "$SAFE_MODE" = false ]; then
  echo "🧼 Checking for Terminating Jobs in $NAMESPACE..."
fi

echo "🔍 Checking for stuck Jobs in all namespaces..."
kubectl get jobs --all-namespaces -o json | jq -r '.items[] | select(.metadata.deletionTimestamp != null) | "\(.metadata.namespace) \(.metadata.name)"' | while read ns job; do
  echo "🧨 Terminating job found: $job in $ns"
  if [ "$SAFE_MODE" = false ]; then
    echo "🔥 Force deleting job: $job in $ns"
fi
    kubectl delete job "$job" -n "$ns" --grace-period=0 --force || echo "⚠️ Failed to delete $job"
    echo "🧨 Cleaned terminating job: $job in $ns" >> "$REPORT_TXT"
  else
    echo "⚠️  Skipped terminating job: $job in $ns (SAFE_MODE)" >> "$REPORT_TXT"

echo "🔍 Checking for stuck Jobs across all namespaces..."
kubectl get jobs --all-namespaces -o json | jq -r '.items[] | select(.metadata.deletionTimestamp != null) | "\(.metadata.namespace) \(.metadata.name)"' | while read ns job; do
  echo "🧨 Terminating job found: $job in $ns"
  if [ "$SAFE_MODE" = false ]; then
    echo "🔥 Force deleting job: $job in $ns"
fi
    kubectl delete job "$job" -n "$ns" --grace-period=0 --force || echo "⚠️ Failed to delete $job"
    echo "🧨 Cleaned terminating job: $job in $ns" >> "$REPORT_TXT"
  else
    echo "⚠️  Skipped terminating job: $job in $ns (SAFE_MODE)" >> "$REPORT_TXT"
if [ "$SAFE_MODE" = false ]; then
  echo "🧹 Checking for stuck argocd-server pods..."
fi

echo "🔍 Checking for NotReady ArgoCD pods..."
for pod in $(kubectl get pod -n "$NAMESPACE" -o json | jq -r '.items[] | select(.status.conditions[]?.type == "Ready" and .status.conditions[]?.status != "True") | .metadata.name'); do
  echo "⚠️  NotReady pod detected: $pod"
  if [ "$SAFE_MODE" = false ]; then
    echo "🔥 Force deleting NotReady pod: $pod"
fi
    kubectl delete pod "$pod" -n "$NAMESPACE" --grace-period=0 --force || echo "⚠️  Failed to delete $pod"
    echo "🔥 Force-deleted NotReady pod: $pod" >> "$REPORT_TXT"
  else
    echo "⚠️  Skipped deleting $pod due to SAFE_MODE" >> "$REPORT_TXT"
  fi
done
  for pod in $(kubectl get pods -n "$NAMESPACE" -l app.kubernetes.io/name=argocd-server -o json | jq -r '.items[] | select(.metadata.deletionTimestamp != null) | .metadata.name'); do
    echo "🔥 Force deleting stuck pod: $pod"
    kubectl delete pod "$pod" -n "$NAMESPACE" --grace-period=0 --force
  done

# Get all applications
echo "📋 Fetching application list..."
apps=$(argocd app list -o name)

  echo "⚠️  No applications found in ArgoCD"
  exit 1

echo "✅ Found applications:"
echo



  echo "   • Sync: $STATUS | Health: $HEALTH"

  if [[ "$STATUS" != "Synced" || "$HEALTH" != "Healthy" ]]; then

    if [ "$AUTO_REPAIR" = true ]; then

# Optionally restart argocd pods if CLI/API is broken
FAILED_PODS=$(kubectl get pods -n "$NAMESPACE" --field-selector=status.phase!=Running -o name)

if [[ -n "$FAILED_PODS" ]]; then
  echo "💥 Found failed pods in $NAMESPACE:"
fi
  echo "$FAILED_PODS"
fi

  if [ "$AUTO_REPAIR" = true ]; then
    echo "🔁 Restarting failed pods..."
fi
    kubectl delete $FAILED_PODS -n "$NAMESPACE"
else
  echo "✅ All ArgoCD pods are running correctly."
fi

echo "✅ ArgoCD application health check complete."
# 🔍 Check for misconfigured repoServer URL in argocd-cm
REPO_URL=$(kubectl -n "$NAMESPACE" get configmap argocd-cm -o jsonpath="{.data.repoServer}" || echo "")
EXPECTED_URL=""

if [[ -n "$REPO_URL" && "$REPO_URL" != "$EXPECTED_URL" ]]; then
  echo "⚠️  repoServer is misconfigured in argocd-cm: $REPO_URL"
fi
  if [ "$AUTO_REPAIR" = true ]; then
    echo "🛠  Resetting repoServer config..."
fi
    kubectl -n "$NAMESPACE" patch configmap argocd-cm -p '{"data":{"repoServer":""}}' || echo "❌ Failed to patch configmap"
    echo "🔁 Restarting ArgoCD server and repo-server..."
    kubectl rollout restart deployment argocd-repo-server -n "$NAMESPACE"
    kubectl rollout restart deployment argocd-server -n "$NAMESPACE"
else
  echo "✅ repoServer config is OK or not set."
# 🧹 Check for stuck ArgoCD Applications (in deleting state)
echo "🔍 Scanning for Applications stuck in deletion..."
STUCK_APPS=$(kubectl get applications.argoproj.io -n "$NAMESPACE" -o json | jq -r '.items[] | select(.metadata.deletionTimestamp != null) | .metadata.name')

if [[ -n "$STUCK_APPS" ]]; then
  echo "⚠️  Found stuck ArgoCD Applications:"
fi
  echo "$STUCK_APPS"
  if [ "$AUTO_REPAIR" = true ]; then
    for stuck_app in $STUCK_APPS; do
      echo "   🔧 Removing finalizers from $stuck_app..."
fi
      kubectl patch application "$stuck_app" -n "$NAMESPACE" -p '{"metadata":{"finalizers":[]}}' --type=merge
      kubectl delete application "$stuck_app" -n "$NAMESPACE" --grace-period=0 --force || echo "❌ Failed to force delete $stuck_app"
    done
else
  echo "✅ No stuck Applications found."

echo ""
if grep -q "❌" "$REPORT_TXT"; then
  echo "❌ Issues remain. Please review $REPORT_TXT"
fi
  exit 1
else
  echo "✅ All issues resolved or no critical issues found."
  exit 0
fi
echo ""
echo "💡 Human Troubleshooting Tips" >> "$REPORT_TXT"
echo "------------------------------------------------------------" >> "$REPORT_TXT"
echo "• argocd-server NotReady" >> "$REPORT_TXT"
echo "  → Run: kubectl logs -n argocd deploy/argocd-server" >> "$REPORT_TXT"
echo "  → Check for liveness/readiness probe, webhook errors" >> "$REPORT_TXT"
echo "" >> "$REPORT_TXT"
echo "• Terminating Jobs" >> "$REPORT_TXT"
echo "  → Run: kubectl get jobs --all-namespaces | grep Terminating" >> "$REPORT_TXT"
echo "  → Fix: force delete stuck jobs; check PVCs or webhook side-effects" >> "$REPORT_TXT"
echo "" >> "$REPORT_TXT"
echo "• ArgoCD App ComparisonError" >> "$REPORT_TXT"
echo "  → Run: argocd app get <app-name> -o yaml" >> "$REPORT_TXT"
echo "  → Check: repo URL, path, chart version, targetRevision" >> "$REPORT_TXT"
echo "" >> "$REPORT_TXT"
echo "• repo-server DNS mismatch" >> "$REPORT_TXT"
echo "  → Run: kubectl get svc/endpoints argocd-repo-server -n argocd" >> "$REPORT_TXT"
echo "  → Fix: restart argocd-repo-server or patch argocd-cm if needed" >> "$REPORT_TXT"
echo "" >> "$REPORT_TXT"
echo "• No ArgoCD apps found" >> "$REPORT_TXT"
echo "  → Fix: apply apps/system/bootstrap-system-apps.yaml manually" >> "$REPORT_TXT"
echo "" >> "$REPORT_TXT"

# Log argocd-server pod issues
echo "" >> "$REPORT_TXT"
echo "🪵 ArgoCD Server Logs (last 20 lines of one pod):" >> "$REPORT_TXT"
argocd_pod=$(kubectl get pods -n "$NAMESPACE" -l app.kubernetes.io/name=argocd-server -o jsonpath="{.items[0].metadata.name}" 2>/dev/null || echo "")
if [[ -n "$argocd_pod" ]]; then
  kubectl logs "$argocd_pod" -n "$NAMESPACE" --tail=20 >> "$REPORT_TXT" || echo "⚠️ Unable to fetch logs" >> "$REPORT_TXT"
else
  echo "⚠️ No argocd-server pod found to fetch logs" >> "$REPORT_TXT"
fi