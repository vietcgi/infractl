#!/bin/bash
set -euo pipefail

echo "🔍 Validating dependencies..."

for cmd in kubectl multipass ansible-playbook yq ssh; do
  if ! command -v $cmd &>/dev/null; then
    echo "❌ Missing dependency: $cmd"
    exit 1
  fi
done

echo "✅ All dependencies are installed."
