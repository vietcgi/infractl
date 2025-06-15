# 🔒 Sealed Secrets

Secure secret management for Kubernetes using [Bitnami Sealed Secrets](https://github.com/bitnami-labs/sealed-secrets).

## 📋 Features

- **Secure by Default**: All secrets are encrypted using 4096-bit RSA keys
- **GitOps Friendly**: Encrypted secrets can be safely stored in Git
- **Automatic Key Rotation**: Built-in support for key rotation
- **RBAC Integration**: Fine-grained access control
- **Monitoring**: Prometheus metrics and alerts
- **High Availability**: Multiple replicas with anti-affinity

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                                                                 │
│  ┌───────────────┐       ┌─────────────────┐                   │
│  │               │       │                 │                   │
│  │  kubeseal CLI │──────▶│  SealedSecret   │───┐               │
│  │               │       │  CustomResource  │   │               │
│  └───────────────┘       └─────────────────┘   │               │
│                                                 │               │
│                                                 ▼               │
│  ┌───────────────┐       ┌─────────────────┐   ┌─────────────────┐
│  │               │       │                 │   │                 │
│  │  Deployment   │       │  Sealed Secrets │   │  Controller     │
│  │  (Your App)   │◀──────│  Controller     │◀───┘                 │
│  │               │       │                 │                       │
│  └───────────────┘       └─────────────────┘                       │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

## 🚀 Quick Start

### Prerequisites

- `kubectl`
- `kubeseal` CLI tool
- Access to a Kubernetes cluster

### Sealing a Secret

1. Create a Kubernetes secret:
   ```bash
   kubectl create secret generic my-secret \
     --dry-run=client \
     --from-literal=username=admin \
     --from-literal=password=secret \
     -o yaml > my-secret.yaml
   ```

2. Seal the secret:
   ```bash
   kubeseal --format=yaml < my-secret.yaml > my-sealed-secret.yaml
   ```

3. Apply the sealed secret:
   ```bash
   kubectl apply -f my-sealed-secret.yaml
   ```

## 🔧 Configuration

### Key Management

- **Key Rotation**: Automatic key rotation every 30 days
- **Key Expiry**: Keys expire after 1 year
- **Key Size**: 4096-bit RSA

### Security Context

- **Run as non-root**: true
- **Read-only root filesystem**: true
- **Privilege escalation**: disabled
- **Capabilities**: All dropped

## 📊 Monitoring

### Metrics

Prometheus metrics are exposed on port `8080`:

- `sealed_secrets_controller_build_info`
- `sealed_secrets_controller_key_rotation_errors_total`
- `sealed_secrets_controller_unseal_errors_total`
- `sealed_secrets_controller_cert_expires_in_seconds`

### Alerts

- **SealedSecretsCertificateExpiry**: Warns 30 days before certificate expiry
- **SealedSecretsKeyRotationFailed**: Alerts on key rotation failures
- **SealedSecretsUnsealErrorRate**: Alerts on high unseal error rates
- **SealedSecretsControllerDown**: Alerts when controller is down

## 🔄 Key Rotation

### Manual Rotation

1. Back up existing keys:
   ```bash
   kubectl get secret -n kube-system -l sealedsecrets.bitnami.com/sealed-secrets-key -o yaml > sealed-secrets-keys-backup-$(date +%Y%m%d).yaml
   ```

2. Trigger key rotation:
   ```bash
   kubectl delete secret -n kube-system -l sealedsecrets.bitnami.com/sealed-secrets-key
   ```

   The controller will automatically generate new keys.

### Automated Rotation

Automated rotation is handled by the controller with the following settings:

```yaml
command:
  - "--key-renew-period=24h"
  - "--key-rotation-period=720h"  # 30 days
  - "--key-expiry=8760h"          # 1 year
```

## 🔒 Security

### Network Policies

- Ingress restricted to kube-system namespace
- Egress restricted to required endpoints
- Instance metadata service blocked

### RBAC

- Minimal permissions required
- Separate roles for controller and users
- Cluster-wide access for controller
- Namespaced access for users

## 📚 Resources

- [Official Documentation](https://github.com/bitnami-labs/sealed-secrets)
- [Security Best Practices](https://github.com/bitnami-labs/sealed-secrets/blob/main/docs/security.md)
- [Key Management](https://github.com/bitnami-labs/sealed-secrets/blob/main/docs/key-management.md)

## 📝 Version Information

- **Chart Version**: See `kustomization.yaml`
- **App Version**: See [VERSIONS.md](../../../../VERSIONS.md)

## 🔄 Upgrading

1. Update the version in `kustomization.yaml`
2. Test with `kustomize build`
3. Review the [changelog](https://github.com/bitnami-labs/sealed-secrets/releases)
4. Commit and push changes

## 🚨 Troubleshooting

### Common Issues

1. **Certificate Expired**
   - Check alerts for `SealedSecretsCertificateExpiry`
   - Follow key rotation procedure

2. **Unseal Errors**
   - Verify the controller is running
   - Check logs: `kubectl logs -n kube-system -l app.kubernetes.io/name=sealed-secrets`

3. **Permission Denied**
   - Verify RBAC permissions
   - Check service account tokens

### Logs

```bash
# Controller logs
kubectl logs -n kube-system -l app.kubernetes.io/name=sealed-secrets

# Events
kubectl get events -n kube-system --field-selector involvedObject.name=sealed-secrets
```

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Push to the branch
5. Create a pull request

## 📄 License

This project is licensed under the [Apache 2.0 License](LICENSE).
