#!/bin/bash
set -e

# Create temp directory
TEMP_DIR=$(mktemp -d)
echo "Using temp directory: $TEMP_DIR"

# Download the latest bundle
BUNDLE_URL="https://github.com/prometheus-operator/prometheus-operator/releases/latest/download/bundle.yaml"
echo "Downloading bundle from $BUNDLE_URL..."
curl -sL $BUNDLE_URL -o "$TEMP_DIR/bundle.yaml"

# Split the bundle into individual files
echo "Splitting bundle into individual CRDs..."
cd "$TEMP_DIR"
csplit -s -z -f crd- -b '%02d.yaml' bundle.yaml "/^---$/" "{*}"

# Process each CRD file
for file in crd-*.yaml; do
    if [ -s "$file" ]; then
        # Get the kind and name from the CRD
        KIND=$(yq e '.kind' "$file")
        NAME=$(yq e '.metadata.name' "$file")
        
        if [ "$KIND" = "CustomResourceDefinition" ] && [ "$NAME" != "null" ]; then
            # Extract the filename from the CRD name
            FILENAME=$(echo "$NAME" | sed 's/\.k8s\.io//' | sed 's/\.monitoring\.coreos\.com//' | tr '.' '-')
            
            # Add annotations
            yq e '.metadata.annotations."argocd.argoproj.io/sync-options" = "SkipDryRunOnMissingResource=true"' "$file" > "$TEMP_DIR/$FILENAME.yaml"
            
            echo "Processed CRD: $NAME -> $FILENAME.yaml"
        fi
    fi
done

# Copy the CRDs to the target directory
echo "Copying CRDs to target directory..."
CRD_TARGET="/Users/kevin/infra/apps/system/base/prometheus-operator-crds/crds"
cp "$TEMP_DIR/"*.yaml "$CRD_TARGET/"

# Clean up
echo "Cleaning up..."
rm -rf "$TEMP_DIR"

echo "CRDs have been updated in $CRD_TARGET"
