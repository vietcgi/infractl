#!/bin/bash

set -euo pipefail

if [ "$#" -lt 2 ]; then
  echo "Usage: $0 -n <namespace> -f <path/to/raw-secret.yaml>"
  exit 1
fi

while getopts "n:f:" opt; do
  case ${opt} in
    n ) namespace=$OPTARG ;;
    f ) secret_file=$OPTARG ;;
    * ) echo "Invalid option"; exit 1 ;;
  esac
done

if ! command -v kubeseal &> /dev/null; then
  echo "kubeseal not found. Install it from https://github.com/bitnami-labs/sealed-secrets"
  exit 1
fi

if [ ! -f "$secret_file" ]; then
  echo "Secret file '$secret_file' not found."
  exit 1
fi

output_file="sealed-secrets/encrypted/$(basename $secret_file .yaml)-sealed.yaml"

echo "🔐 Sealing $secret_file into $output_file..."
kubeseal --format yaml --namespace "$namespace" < "$secret_file" > "$output_file"
echo "✅ Sealed secret saved to $output_file"
