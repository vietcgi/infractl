# 📦 Longhorn (Helm Chart)

Helm-based deployment of Longhorn distributed block storage for Kubernetes.

## 🔗 Chart Info

- Chart: `longhorn`
- Repository: `https://charts.longhorn.io`
- Version: `1.9.0` (latest stable)

## 🚀 How to Upgrade

1. Update the version in `kustomization.yaml`
2. Test with `kustomize build`
3. Commit and push

## ⚙️ Configuration

Default values are set in `values.yaml`. Override values in environment-specific overlays.

## 🔐 Secrets

If secrets are used (e.g., backup credentials), they should be stored as SealedSecrets in `overlays/<env>/longhorn-helm/`.
