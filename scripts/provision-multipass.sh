#!/bin/bash
set -euo pipefail

CLUSTER_FILE="${CLUSTER_FILE:-cluster.yaml}"
SSH_KEY_PATH="${HOME}/.ssh/id_rsa.pub"

if [ ! -f "$SSH_KEY_PATH" ]; then
  echo "❌ SSH key not found at $SSH_KEY_PATH"
  echo "➡️  Generate one with: ssh-keygen -t rsa -b 4096"
  exit 1
fi

# Default to Ubuntu 22.04 unless overridden in YAML
DEFAULT_OS="22.04"
OS_VERSION=$(yq '.os // "'"$DEFAULT_OS"'"' "$CLUSTER_FILE")

echo "📖 Reading cluster config from $CLUSTER_FILE..."
NODES=$(yq -o=json '.masters + .workers' "$CLUSTER_FILE" | jq -c '.[]')

for node in $NODES; do
  NAME=$(echo "$node" | jq -r '.name')
  MODE=$(echo "$node" | jq -r '.mode')

  if [[ "$MODE" == "multipass" ]]; then
    echo "⚙️  Checking $NAME..."
    if ! multipass info "$NAME" &>/dev/null; then
      echo "🚀 Launching $NAME via Multipass (Ubuntu $OS_VERSION)..."
      multipass launch "$OS_VERSION" --name "$NAME" --cpus 2 --mem 4G --disk 20G --cloud-init - <<EOF
#cloud-config
users:
  - name: ubuntu
    ssh-authorized-keys:
      - $(cat "$SSH_KEY_PATH")
    sudo: ALL=(ALL) NOPASSWD:ALL
    shell: /bin/bash
EOF
    else
      echo "✅ $NAME already exists"
    fi

    echo "🔧 Installing dependencies on $NAME..."
    multipass exec "$NAME" -- sudo apt-get update -y
    multipass exec "$NAME" -- sudo apt-get install -y python3 python3-pip curl
    multipass exec "$NAME" -- sudo ln -sf /usr/bin/python3 /usr/bin/python
  fi
done

echo "✅ All Multipass VMs ready."
