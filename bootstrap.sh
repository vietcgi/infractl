#!/bin/bash
set -euo pipefail

CLUSTER_FILE="${1:-cluster.yaml}"
export CLUSTER_FILE
CLUSTER_BASENAME=$(basename "$CLUSTER_FILE")
CLUSTER_NAME="${CLUSTER_BASENAME%%.*}"
INVENTORY_FILE="ansible/hosts-${CLUSTER_NAME}.ini"
GROUP_VARS_FILE="ansible/group_vars/${CLUSTER_NAME}.yml"
KUBECONFIG_PATH="$HOME/.kube/rke2-${CLUSTER_NAME}.yaml"
LOGFILE="logs/bootstrap-${CLUSTER_NAME}-$(date +%Y%m%d-%H%M%S).log"
mkdir -p logs
exec > >(tee -a "$LOGFILE") 2>&1


mkdir -p logs
CLUSTER_FILE="${1:-cluster.yaml}"
export CLUSTER_FILE
CLUSTER_BASENAME=$(basename "$CLUSTER_FILE")
CLUSTER_NAME="${CLUSTER_BASENAME%%.*}"
INVENTORY_FILE="ansible/hosts-${CLUSTER_NAME}.ini"
GROUP_VARS_FILE="ansible/group_vars/${CLUSTER_NAME}.yml"
KUBECONFIG_PATH="$HOME/.kube/rke2-${CLUSTER_NAME}.yaml"
LOGFILE="logs/bootstrap-${CLUSTER_NAME}-$(date +%Y%m%d-%H%M%S).log"
mkdir -p logs
CLUSTER_BASENAME=$(basename "$CLUSTER_FILE")
CLUSTER_NAME="${CLUSTER_BASENAME%%.*}"
INVENTORY_FILE="ansible/hosts-${CLUSTER_NAME}.ini"
export INVENTORY_FILE
# 💡 Ensure Ansible role lablabs.rke2 is installed before running playbook
ROLE_PATH="ansible/roles/lablabs.rke2"
if [ ! -d "$ROLE_PATH" ]; then
  echo "📥 Installing Ansible role lablabs.rke2..."
  ansible-galaxy install lablabs.rke2 -p ansible/roles
fi

if [[ "${CLEAN:-false}" == "true" ]]; then
  ./scripts/cleanup-multipass.sh $CLUSTER_FILE
fi


echo "🚀 Starting full RKE2 GitOps bootstrap..."

./scripts/validate-deps.sh
./scripts/parse-cluster.sh $CLUSTER_FILE
./scripts/provision-nodes.sh $CLUSTER_FILE
./scripts/generate-inventory.sh $CLUSTER_FILE $INVENTORY_FILE
./scripts/run-ansible.sh $CLUSTER_FILE $INVENTORY_FILE $GROUP_VARS_FILE
./scripts/export-kubeconfig.sh $CLUSTER_FILE $KUBECONFIG_PATH
./scripts/install-argocd.sh
./scripts/patch-argocd-password.sh

echo "✅ Bootstrap complete!"
