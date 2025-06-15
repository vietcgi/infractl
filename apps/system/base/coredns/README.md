# 📦 Coredns

Helm-based deployment of `coredns` via Kustomize.

## 🔗 Chart Info

- Chart repo: defined in `kustomization.yaml`
- Version: see [`VERSIONS.md`](../../../../VERSIONS.md)

## 🚀 How to Upgrade

1. Update the version in `kustomization.yaml`
2. Test with `kustomize build`
3. Commit and push

## 🔐 Secrets

If secrets are used (e.g., admin credentials), they are stored as SealedSecrets in `overlays/dev|prod/coredns`.

---
