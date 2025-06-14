#!/bin/bash

# Define the base directory
BASE_DIR="/Users/kevin/infra/apps/system/overlays/prod/dc11a"

# List of missing applications
APPS=(
  "alertmanager"
  "cert-manager-crds"
  "cilium"
  "coredns"
  "neuvector"
  "nginx-ingress"
  "nodelocaldns"
  "prometheus"
  "prometheus-operator-crds"
  "rancher"
  "sealed-secrets"
)

# Create directories and kustomization.yaml files
for APP in "${APPS[@]}"; do
  # Create the directory if it doesn't exist
  mkdir -p "${BASE_DIR}/${APP}"
  
  # Create a basic kustomization.yaml file
  cat > "${BASE_DIR}/${APP}/kustomization.yaml" <<EOL
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

nameSuffix: -dc11a

resources:
- ../../../../base/${APP}
EOL
  
  echo "Created ${BASE_DIR}/${APP}/kustomization.yaml"
done

echo "All application directories and kustomization.yaml files have been created."
