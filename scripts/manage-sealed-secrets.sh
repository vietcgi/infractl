#!/bin/bash
set -euo pipefail

# === Configuration ===
readonly SCRIPT_NAME=$(basename "$0")
readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly CERT_DAYS=365
readonly RENEW_DAYS=30
readonly KEY_SIZE=4096

# Colors for output
readonly RED='\033[0;31m'
readonly GREEN='\033[0;32m'
readonly YELLOW='\033[1;33m'
readonly NC='\033[0m' # No Color

# === Logging functions ===
log_info() {
    echo -e "${GREEN}[INFO]${NC} $(date -u +'%Y-%m-%dT%H:%M:%SZ') $*"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $(date -u +'%Y-%m-%dT%H:%M:%SZ') $*" >&2
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $(date -u +'%Y-%m-%dT%H:%M:%SZ') $*" >&2
    exit 1
}

# === Check prerequisites ===
check_prerequisites() {
    local required_commands=("kubectl" "openssl" "jq")
    local missing_commands=()
    
    for cmd in "${required_commands[@]}"; do
        if ! command -v "$cmd" &> /dev/null; then
            missing_commands+=("$cmd")
        fi
    done
    
    if [ ${#missing_commands[@]} -gt 0 ]; then
        log_error "Missing required commands: ${missing_commands[*]}"
    fi
    
    # Check Kubernetes connectivity
    if ! kubectl cluster-info &> /dev/null; then
        log_error "Cannot connect to Kubernetes cluster. Check your kubeconfig."
    fi
}

# === Generate new certificate ===
generate_certificate() {
    local key_file=$1
    local cert_file=$2
    local days=$3
    
    log_info "Generating new certificate valid for ${days} days..."
    
    openssl req -x509 \
        -newkey "rsa:$KEY_SIZE" \
        -keyout "$key_file" \
        -out "$cert_file" \
        -days "$days" \
        -nodes \
        -subj "/CN=sealed-secrets" \
        -addext "keyUsage=digitalSignature,keyEncipherment" \
        -addext "extendedKeyUsage=serverAuth" \
        -addext "subjectAltName=DNS:sealed-secrets"
    
    # Set secure permissions
    chmod 600 "$key_file"
    
    log_info "Certificate generated successfully"
    log_info "Certificate valid until: $(openssl x509 -enddate -noout -in "$cert_file" | cut -d= -f2)"
}

# === Backup existing keys ===
backup_existing_keys() {
    local backup_dir="${SCRIPT_DIR}/../backups/sealed-secrets/$(date +%Y%m%d-%H%M%S)"
    mkdir -p "$backup_dir"
    
    log_info "Backing up existing sealed secrets keys to $backup_dir"
    
    # Backup secrets
    kubectl get secret -n kube-system -l sealedsecrets.bitnami.com/sealed-secrets-key -o yaml > "${backup_dir}/sealed-secrets-keys.yaml"
    
    # Backup CRD
    kubectl get crd sealedsecrets.bitnami.com -o yaml > "${backup_dir}/sealedsecrets-crd.yaml" || true
    
    log_info "Backup completed successfully"
}

# === Rotate keys ===
rotate_keys() {
    log_info "Starting key rotation..."
    
    # Backup existing keys
    backup_existing_keys
    
    # Delete existing secrets to trigger rotation
    log_info "Deleting existing sealed secrets keys..."
    kubectl delete secret -n kube-system -l sealedsecrets.bitnami.com/sealed-secrets-key
    
    # Wait for new keys to be generated
    log_info "Waiting for new keys to be generated..."
    local max_retries=30
    local count=0
    
    while [ $count -lt $max_retries ]; do
        if kubectl get secret -n kube-system -l sealedsecrets.bitnami.com/sealed-secrets-key &> /dev/null; then
            log_info "New keys generated successfully"
            return 0
        fi
        
        count=$((count + 1))
        sleep 2
    done
    
    log_error "Failed to generate new keys after $max_retries attempts"
    return 1
}

# === Check certificate expiration ===
check_cert_expiry() {
    local secret_name
    secret_name=$(kubectl get secret -n kube-system -l sealedsecrets.bitnami.com/sealed-secrets-key -o name | head -n 1)
    
    if [ -z "$secret_name" ]; then
        log_error "No sealed secrets keys found"
        return 1
    fi
    
    local cert_data
    cert_data=$(kubectl get "$secret_name" -n kube-system -o jsonpath='{.data.tls\.crt}' | base64 -d)
    
    local expiry_seconds
    expiry_seconds=$(echo "$cert_data" | openssl x509 -checkend 0 -noout -enddate | cut -d= -f2 | xargs -I {} date -d "{}" +%s)
    local now_seconds=$(date +%s)
    local days_remaining=$(( (expiry_seconds - now_seconds) / 86400 ))
    
    echo "$days_remaining"
}

# === Main function ===
main() {
    local action="${1:-help}"
    
    check_prerequisites
    
    case "$action" in
        generate)
            local key_file="${2:-./sealed-secrets.key}"
            local cert_file="${3:-./sealed-secrets.crt}"
            generate_certificate "$key_file" "$cert_file" "$CERT_DAYS"
            ;;
            
        backup)
            backup_existing_keys
            ;;
            
        rotate)
            rotate_keys
            ;;
            
        check-expiry)
            local days_left
            days_left=$(check_cert_expiry || echo "-1")
            
            if [ "$days_left" -eq -1 ]; then
                log_error "Failed to check certificate expiration"
                exit 1
            fi
            
            if [ "$days_left" -le "$RENEW_DAYS" ]; then
                log_warn "Certificate expires in $days_left days (renewal threshold: $RENEW_DAYS days)"
                exit 1
            else
                log_info "Certificate is valid for $days_left days"
            fi
            ;;
            
        *)
            echo "Usage: $0 <command> [args...]"
            echo ""
            echo "Commands:"
            echo "  generate [key_file] [cert_file]  Generate new certificate and key"
            echo "  backup                          Backup existing sealed secrets keys"
            echo "  rotate                          Rotate sealed secrets keys"
            echo "  check-expiry                   Check certificate expiration"
            echo "  help                            Show this help message"
            exit 1
            ;;
    esac
}

# Run main function
main "$@"
