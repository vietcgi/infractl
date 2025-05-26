#!/bin/bash
set -euo pipefail

CLUSTER_FILE="${1:-cluster.yaml}"
INVENTORY_FILE="${2:-ansible/hosts-cluster.ini}"
GROUP_VARS_FILE="${3:-}"

source ./scripts/parse-cluster.sh

CLUSTER_BASENAME=$(basename "$CLUSTER_FILE")
CLUSTER_NAME="${CLUSTER_BASENAME%%.*}"

if [ -z "$GROUP_VARS_FILE" ]; then
  GROUP_VARS_FILE="ansible/group_vars/${CLUSTER_NAME}.yml"
fi

# Dynamically resolve master1 IP
BOOTSTRAP_MASTER=$(yq '.masters[0].name' "$CLUSTER_FILE")
BOOTSTRAP_IP=$(multipass info "$BOOTSTRAP_MASTER" | awk '/IPv4/ {print $2}')
RKE2_SERVER_URL="https://$BOOTSTRAP_IP:9345"

# Resolve TLS SANs from inventory
MASTER_IPS=$(awk '/^\[masters\]/ {found=1; next} /^\[|^$/{found=0} found {for(i=1;i<=NF;i++) if ($i ~ /^ansible_host=/) print $i}' "$INVENTORY_FILE" | cut -d= -f2)
TLS_SAN_LIST=$(printf -- "- %s\n" $MASTER_IPS)

# Generate per-cluster group vars
mkdir -p "$(dirname "$GROUP_VARS_FILE")"
cat > "$GROUP_VARS_FILE" <<EOF
rke2_version: "$K8S_VERSION"
rke2_token: "$CLUSTER_TOKEN"
rke2_cni: "$CNI_PLUGIN"
rke2_servers:
  - $RKE2_SERVER_URL
rke2_tls_san:
$TLS_SAN_LIST
rke2_download_kubeconf: true
EOF

echo "📡 Using bootstrap master: $BOOTSTRAP_MASTER ($BOOTSTRAP_IP)"
echo "📄 Cluster-specific group vars written to $GROUP_VARS_FILE"
echo "🚀 Running Ansible playbook with --extra-vars=@$GROUP_VARS_FILE"

#ANSIBLE_HOST_KEY_CHECKING=False ansible-playbook -i "$INVENTORY_FILE" ansible/playbook.yml   --extra-vars="@$GROUP_VARS_FILE"
