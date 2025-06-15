#!/bin/bash
set -euo pipefail

# === Configuration ===
readonly SCRIPT_NAME=$(basename "$0")
readonly CERT_DAYS=365  # 1 year validity
readonly RENEW_DAYS=30  # Start renewing 30 days before expiry
readonly KEY_SIZE=4096  # 4096-bit RSA key

# === Initialize logging ===
log() {
    echo "[$(date +'%Y-%m-%dT%H:%M:%S%z')] $*" >&2
}

# === Validate inputs ===
validate_inputs() {
    # Required environment variables
    local required_vars=(
        "CLUSTER_NAME"
        "OKTA_CLIENT_ID"
        "OKTA_CLIENT_SECRET"
    )
    
    for var in "${required_vars[@]}"; do
        if [[ -z "${!var:-}" ]]; then
            log "ERROR: Required variable $var is not set"
            return 1
        fi
    done

    # Validate cluster name format (dcXXa format)
    if [[ ! "$CLUSTER_NAME" =~ ^dc[0-9]{2}[a-z]$ ]]; then
        log "ERROR: Invalid cluster name format. Expected format: dcXXa (e.g., dc11a)"
        return 1
    fi
}

# === Generate secure temporary file ===
create_temp_file() {
    local prefix=$1
    mktemp "/tmp/${SCRIPT_NAME}.${prefix}.XXXXXXXXXX"
}

# === Main script ===
main() {
    local cluster_name="${1:-dc11a}"
    local output_dir="apps/gitops/argocd/prod/secrets"
    local keypair_dir=".sealedsecrets-keypair"
    local secret_name="okta-sso-secret"
    
    # Export for validate_inputs
    export CLUSTER_NAME="$cluster_name"
    
    # Validate inputs
    validate_inputs || exit 1
    
    # Create directories if they don't exist
    mkdir -p "$keypair_dir" "$output_dir"
    
    # Create secure temp file
    local temp_secret
    temp_secret=$(create_temp_file "secret")
    trap 'rm -f "$temp_secret"' EXIT
    
    # Generate or reuse certificate
    if [[ ! -f "$keypair_dir/controller.crt" || ! -f "$keypair_dir/controller.key" ]]; then
        log "Generating new Sealed Secrets certificate/key pair with ${CERT_DAYS}-day validity..."
        openssl req -x509 -newkey "rsa:$KEY_SIZE" \
            -keyout "$keypair_dir/controller.key" \
            -out "$keypair_dir/controller.crt" \
            -days "$CERT_DAYS" -nodes \
            -subj "/CN=sealed-secrets" \
            -addext "keyUsage=digitalSignature,keyEncipherment" \
            -addext "extendedKeyUsage=serverAuth" \
            -addext "subjectAltName=DNS:sealed-secrets"
        
        # Set secure permissions
        chmod 600 "$keypair_dir/controller.key"
        log "Generated new certificate valid until: $(openssl x509 -enddate -noout -in "$keypair_dir/controller.crt" | cut -d= -f2)"
    else
        log "Using existing certificate/key pair in $keypair_dir"
        log "Certificate valid until: $(openssl x509 -enddate -noout -in "$keypair_dir/controller.crt" | cut -d= -f2)"
    fi
    
    # Create unsealed Secret manifest
    cat <<-EOF > "$temp_secret"
    apiVersion: v1
    kind: Secret
    metadata:
      name: $secret_name
      namespace: argocd
      labels:
        app.kubernetes.io/name: argocd
        app.kubernetes.io/component: sso
        sealedsecrets.bitnami.com/sealed-secrets-key: "sealed-secrets-key"
    type: Opaque
    stringData:
      clientID: "$OKTA_CLIENT_ID"
      clientSecret: "$OKTA_CLIENT_SECRET"
    EOF
    
    # Seal the secret
    local output_file="${output_dir}/sealed-okta-${cluster_name}.yaml"
    kubeseal \
        --cert "$keypair_dir/controller.crt" \
        --scope cluster-wide \
        -o yaml < "$temp_secret" \
        > "$output_file"
    
    # Verify the sealed secret
    if [[ -s "$output_file" ]]; then
        log "✅ Sealed secret saved to $output_file"
        log "To apply: kubectl apply -f $output_file"
        return 0
    else
        log "❌ Failed to create sealed secret"
        return 1
    fi
}

# Run main function
main "$@"

