#!/bin/bash
set -euo pipefail

CLUSTER_FILE="${1:-cluster.yaml}"

echo "💣 NUKING all Multipass nodes from $CLUSTER_FILE..."

NODES=$(yq -o=json '.masters + .workers' "$CLUSTER_FILE" | jq -c '.[]')
for node in $NODES; do
  NAME=$(echo "$node" | jq -r '.name')
  MODE=$(echo "$node" | jq -r '.mode')

  if [[ "$MODE" == "multipass" ]]; then
    echo "🗑️ Deleting multipass instance: $NAME"
    multipass delete "$NAME" || echo "⚠️ Not found: $NAME"
  fi
done

echo "♻️ Purging unused instances..."
multipass purge

echo "✅ Multipass cleanup complete."

CLUSTER_BASENAME=$(basename "$CLUSTER_FILE")
CLUSTER_NAME="${CLUSTER_BASENAME%%.*}"
INVENTORY_FILE="ansible/hosts-${CLUSTER_NAME}.ini"

if [ -f "$INVENTORY_FILE" ]; then
  echo "🧹 Removing inventory file: $INVENTORY_FILE"
  rm -f "$INVENTORY_FILE"
fi
