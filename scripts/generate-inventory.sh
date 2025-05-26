CLUSTER_FILE="${1:-cluster.yaml}"
INVENTORY_FILE="${2:-ansible/hosts-cluster.ini}"
#!/bin/bash
set -euo pipefail
source ./scripts/parse-cluster.sh

CLUSTER_BASENAME=$(basename "$CLUSTER_FILE")
CLUSTER_NAME="${CLUSTER_BASENAME%%.*}"
export INVENTORY_FILE

echo "📄 Generating Ansible inventory for $CLUSTER_NAME into $INVENTORY_FILE..."

echo "[masters]" > "$INVENTORY_FILE"
for node_json in $(echo "$MASTER_NODES" | jq -c '.[]'); do
  NAME=$(echo "$node_json" | jq -r '.name')
  MODE=$(echo "$node_json" | jq -r '.mode')
  if [[ "$MODE" == "multipass" ]]; then
    IP=$(multipass info "$NAME" | awk '/IPv4/ {print $2}')
  elif [[ "$MODE" == "docker" ]]; then
    IP=$(docker inspect -f '{{range.NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$NAME")
  else
    IP=$(echo $node_json | jq -r '.ip')
  fi
  echo "$NAME ansible_host=$IP ansible_user=ubuntu ansible_private_key_file=~/.ssh/id_rsa" >> "$INVENTORY_FILE"
done

echo "[workers]" >> "$INVENTORY_FILE"
for node_json in $(echo "$WORKER_NODES" | jq -c '.[]'); do
  NAME=$(echo "$node_json" | jq -r '.name')
  MODE=$(echo "$node_json" | jq -r '.mode')
  if [[ "$MODE" == "multipass" ]]; then
    IP=$(multipass info "$NAME" | awk '/IPv4/ {print $2}')
  elif [[ "$MODE" == "docker" ]]; then
    IP=$(docker inspect -f '{{range.NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$NAME")
  else
    IP=$(echo $node_json | jq -r '.ip')
  fi
  echo "$NAME ansible_host=$IP ansible_user=ubuntu ansible_private_key_file=~/.ssh/id_rsa" >> "$INVENTORY_FILE"
done

cat <<EOF >> "$INVENTORY_FILE"

[k8s_cluster:children]
masters
workers
EOF

echo "✅ Inventory written to $INVENTORY_FILE"
