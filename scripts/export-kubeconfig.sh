#!/bin/bash
set -euo pipefail
CLUSTER_FILE="${CLUSTER_FILE:-cluster.yaml}"

echo "💾 Exporting kubeconfig..."

NAME=$(yq '.masters[0].name' "$CLUSTER_FILE")
MODE=$(yq '.masters[0].mode' "$CLUSTER_FILE")

if [[ "$MODE" == "multipass" ]]; then
  MASTER_IP=$(multipass info "$NAME" | awk '/IPv4/ {print $2}')
else
  MASTER_IP=$(yq '.masters[0].ip' "$CLUSTER_FILE")
fi

KCFG=~/.kube/rke2.yaml
mkdir -p ~/.kube
ssh ubuntu@$MASTER_IP "sudo cat /etc/rancher/rke2/rke2.yaml" > $KCFG
sed -i.bak "s/127.0.0.1/$MASTER_IP/g" $KCFG

echo "🔑 KUBECONFIG exported to $KCFG"
echo "👉 Run: export KUBECONFIG=$KCFG && kubectl get nodes"
