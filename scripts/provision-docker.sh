#!/bin/bash
set -euo pipefail

CLUSTER_FILE="${1:-cluster.yaml}"
SSH_KEY_PATH="${HOME}/.ssh/id_rsa.pub"

echo "🐳 Provisioning Docker-based RKE2 nodes from $CLUSTER_FILE..."

NODES=$(yq -o=json '.masters + .workers' "$CLUSTER_FILE" | jq -c '.[]')

for node in $NODES; do
  NAME=$(echo "$node" | jq -r '.name')
  MODE=$(echo "$node" | jq -r '.mode')

  if [[ "$MODE" == "docker" ]]; then
    echo "🛠️  Launching Docker container for node: $NAME"
    docker run -d --privileged --name "$NAME" --hostname "$NAME"       --tmpfs /run --tmpfs /run/lock --volume /sys/fs/cgroup:/sys/fs/cgroup:ro       ubuntu:22.04 sleep infinity

    echo "🔧 Installing SSH & base packages in $NAME"
    docker exec "$NAME" apt-get update
    docker exec "$NAME" apt-get install -y openssh-server python3 curl

    echo "🔐 Configuring SSH in $NAME"
    docker exec "$NAME" mkdir -p /root/.ssh
    docker cp "$SSH_KEY_PATH" "$NAME:/root/.ssh/authorized_keys"
    docker exec "$NAME" chmod 600 /root/.ssh/authorized_keys
    docker exec "$NAME" service ssh start
  fi
done

echo "✅ Docker-based RKE2 nodes are up."
