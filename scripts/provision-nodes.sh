#!/bin/bash
set -euo pipefail

CLUSTER_FILE="${1:-cluster.yaml}"
NODES=$(yq -o=json '.masters + .workers' "$CLUSTER_FILE" | jq -c '.[]')

MODES=$(echo "$NODES" | jq -r '.mode' | sort -u | uniq)

for MODE in $MODES; do
  case "$MODE" in
    multipass)
      echo "📦 Using multipass provisioner..."
      ./scripts/provision-multipass.sh "$CLUSTER_FILE"
      ;;
    prod)
      echo "📡 Skipping provisioning for prod nodes. Ensure SSH access is configured."
      ;;
    docker)
      echo "🐳 Using docker provisioner..."
      ./scripts/provision-docker.sh "$CLUSTER_FILE"
      ;;
    *)
      echo "❌ Unsupported mode: $MODE"
      exit 1
      ;;
  esac
done
