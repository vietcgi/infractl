#!/bin/bash

set -euo pipefail

echo "🔍 Running ansible-lint on playbook and inventory..."
if ! command -v ansible-lint &> /dev/null; then
  echo "Installing ansible-lint..."
  pip3 install ansible-lint
fi

ansible-lint ansible/playbook.yml
