#!/bin/bash

# Script to replicate component configurations from dc11a to dc11b
# Handles both direct kustomize resources and Helm chart dependencies
# Usage: ./replicate_dc11a_to_dc11b.sh <component_name>

set -e

if [ $# -eq 0 ]; then
    echo "Usage: $0 <component_name>"
    echo "Available components in dc11a:"
    ls -1 /Users/kevin/infra/apps/system/overlays/prod/dc11a/ | grep -v 'values.yaml'
    exit 1
fi

COMPONENT=$1
SRC_DIR="/Users/kevin/infra/apps/system/overlays/prod/dc11a/${COMPONENT}"
DEST_DIR="/Users/kevin/infra/apps/system/overlays/prod/dc11b/${COMPONENT}"

if [ ! -d "$SRC_DIR" ]; then
    echo "Error: Component '$COMPONENT' not found in dc11a"
    exit 1
fi

if [ -d "$DEST_DIR" ]; then
    echo "Warning: Destination directory '$DEST_DIR' already exists"
    read -p "Do you want to continue? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
    rm -rf "$DEST_DIR"
fi

echo "Copying $COMPONENT from dc11a to dc11b..."
mkdir -p "$DEST_DIR"

# Copy all files, replacing dc11a with dc11b
find "$SRC_DIR" -type f | while read -r file; do
    dest="${DEST_DIR}/$(basename "$file")"
    mkdir -p "$(dirname "$dest")"
    
    # Handle different file types
    case "$file" in
        *.yaml|*.yml|*.json|*.yaml.tpl|*.tpl|*.txt|*.md)
            # Process text files with replacements
            sed -e "s/dc11a/dc11b/g" \
                -e "s/namespace: .*/namespace: ${COMPONENT}/g" \
                "$file" > "$dest"
            ;;
        *)
            # Copy binary files as-is
            cp "$file" "$dest"
            ;;
    esac
    
    # Make sure the file is readable
    chmod 644 "$dest"
    echo "Created: $dest"
done

# Handle Helm chart dependencies
if [ -f "${DEST_DIR}/kustomization.yaml" ] && grep -q "helmCharts:" "${DEST_DIR}/kustomization.yaml"; then
    echo "\n⚠️  Component uses Helm charts. Additional setup may be required:"
    echo "1. Verify Helm repository is added:"
    echo "   helm repo add <repo-name> <repo-url>"
    echo "2. Update Helm dependencies:"
    echo "   helm dependency update ${DEST_DIR}/"
    echo "3. Verify values in ${DEST_DIR}/values.yaml"
fi

echo "\nVerifying kustomize build..."
if kustomize build "$DEST_DIR" > /dev/null 2>&1; then
    echo "✅ Success: kustomize build completed successfully"
else
    echo "❌ Error: kustomize build failed"
    exit 1
fi

echo "\nComponent '$COMPONENT' has been replicated to dc11b"
echo "Please review the changes and commit them to version control"
