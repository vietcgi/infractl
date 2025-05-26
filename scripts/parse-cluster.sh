#!/bin/bash
set -euo pipefail

CLUSTER_FILE="${1:-cluster.yaml}"
export K8S_VERSION=$(yq '.kubernetes_version' $CLUSTER_FILE)
export CNI_PLUGIN=$(yq '.cni' $CLUSTER_FILE)
export CLUSTER_TOKEN=$(yq '.token' $CLUSTER_FILE)

export MASTER_NODES=$(yq -o=json '.masters' $CLUSTER_FILE)
export WORKER_NODES=$(yq -o=json '.workers' $CLUSTER_FILE)

echo "🔧 Parsed cluster.yaml:"
echo "- Kubernetes version: $K8S_VERSION"
echo "- CNI: $CNI_PLUGIN"
echo "- Masters: $(echo $MASTER_NODES | jq length)"
echo "- Workers: $(echo $WORKER_NODES | jq length)"
