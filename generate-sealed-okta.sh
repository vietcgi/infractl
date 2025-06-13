#!/bin/bash
set -euo pipefail

# === Configuration ===
CLUSTER_NAME="${1:-dc11a}"
OUTPUT_DIR="apps/gitops/argocd/prod/secrets"
KEYPAIR_DIR=".sealedsecrets-keypair"
SECRET_NAME="okta-sso-secret"

# Dummy values – replace or use environment vars
OKTA_CLIENT_ID="${OKTA_CLIENT_ID:-example-client-id}"
OKTA_CLIENT_SECRET="${OKTA_CLIENT_SECRET:-example-client-secret}"

mkdir -p "$KEYPAIR_DIR" "$OUTPUT_DIR"

# === Step 1: Generate static cert/key if not already exists ===
if [[ ! -f "$KEYPAIR_DIR/controller.crt" || ! -f "$KEYPAIR_DIR/controller.key" ]]; then
  echo "[*] Generating new Sealed Secrets certificate/key pair..."
  openssl req -x509 -newkey rsa:4096 \
    -keyout "$KEYPAIR_DIR/controller.key" \
    -out "$KEYPAIR_DIR/controller.crt" \
    -days 3650 -nodes \
    -subj "/CN=sealed-secrets"
else
  echo "[*] Reusing existing certificate/key pair in $KEYPAIR_DIR"
fi

# === Step 2: Create unsealed Secret manifest ===
cat <<EOF > /tmp/okta-unsealed-${CLUSTER_NAME}.yaml
apiVersion: v1
kind: Secret
metadata:
  name: $SECRET_NAME
  namespace: argocd
  labels:
    sealedsecrets.bitnami.com/sealed-secrets-key: "sealed-secrets-key"
type: Opaque
stringData:
  clientID: "$OKTA_CLIENT_ID"
  clientSecret: "$OKTA_CLIENT_SECRET"
EOF

# === Step 3: Seal the secret ===
kubeseal --cert "$KEYPAIR_DIR/controller.crt" \
  -o yaml < /tmp/okta-unsealed-${CLUSTER_NAME}.yaml \
  > "${OUTPUT_DIR}/sealed-okta-${CLUSTER_NAME}.yaml"

echo "[✔] Sealed secret saved to ${OUTPUT_DIR}/sealed-okta-${CLUSTER_NAME}.yaml"

