# 🔐 Sealed Secrets Automation for GitOps – Okta Integration

This repository contains tooling and manifests for managing sensitive secrets using [Bitnami Sealed Secrets](https://github.com/bitnami-labs/sealed-secrets) in a GitOps-friendly way via ArgoCD.

The primary use case is securely storing and deploying Okta SSO credentials to your ArgoCD instance in a declarative, encrypted form.

---

## 📁 Directory Structure

```
.
├── generate-sealed-okta.sh                 # Script to generate SealedSecret
├── .sealedsecrets-keypair/                # Local keypair (do not commit the private key)
│   ├── controller.crt                     # Public certificate used to seal secrets
│   └── controller.key                     # Private key used by the controller (DO NOT COMMIT)
├── apps/
│   ├── gitops/argocd/prod/secrets/
│   │   └── sealed-okta-<CLUSTER>.yaml     # Output sealed secret (safe for Git)
│
├── apps/system/base/sealed-secrets/
│   ├── kustomization.yaml                 # Helm-based sealed-secrets install
│   └── values.yaml                        # Reference existing TLS secret
```

---

## 🛠️ Prerequisites

- Kubernetes cluster with ArgoCD installed
- [kubeseal](https://github.com/bitnami-labs/sealed-secrets#kubeseal) CLI
- `openssl`
- `bash`
- Public/private TLS key pair for sealed secrets (will be generated if not present)
- Sealed Secrets controller installed via ArgoCD **before** applying `SealedSecret`

---


## 🔰 Bootstrap Step (Pre-Install)

Before ArgoCD installs the Sealed Secrets controller, you must pre-create the TLS secret so the controller picks it up instead of auto-generating a new key.

### Step:

```bash
kubectl -n kube-system create secret tls sealed-secrets-key \
  --cert=.sealedsecrets-keypair/controller.crt \
  --key=.sealedsecrets-keypair/controller.key
```

This must be run **before** ArgoCD syncs the `sealed-secrets` app. Otherwise, the controller will generate its own keypair, and your pre-sealed secrets will not decrypt.


## 🚀 Usage

### 1. Prepare Environment

Set the required secrets via environment variables:

```bash
export OKTA_CLIENT_ID="your-client-id"
export OKTA_CLIENT_SECRET="your-client-secret"
```

### 2. Run the Script

```bash
./generate-sealed-okta.sh <CLUSTER_NAME>
```

Example:

```bash
./generate-sealed-okta.sh dc11a
```

This will:

- Generate `controller.crt` and `controller.key` if missing
- Create a temporary unsealed Secret
- Generate a sealed YAML at:
  ```
  apps/gitops/argocd/prod/secrets/sealed-okta-dc11a.yaml
  ```

---

## 🔐 How the Sealing Works

- `kubeseal` encrypts the `Secret` using the public certificate (`controller.crt`)
- The resulting `SealedSecret` is stored in Git and synced into the cluster via ArgoCD
- The Sealed Secrets controller decrypts it using the private key (`controller.key`), loaded from a pre-created Kubernetes TLS Secret

---

## 🧩 How Sealed Secrets Is Deployed (Helm via Kustomize)

```yaml
# apps/system/base/sealed-secrets/kustomization.yaml
helmCharts:
  - name: sealed-secrets
    repo: https://bitnami-labs.github.io/sealed-secrets
    version: 2.15.3
    releaseName: sealed-secrets
    namespace: kube-system
    valuesFile: values.yaml
```

```yaml
# apps/system/base/sealed-secrets/values.yaml
existingCertSecret: sealed-secrets-key
```

The Sealed Secrets controller expects a pre-existing secret:

```bash
kubectl -n kube-system create secret tls sealed-secrets-key \
  --cert=.sealedsecrets-keypair/controller.crt \
  --key=.sealedsecrets-keypair/controller.key
```

> You must run this **before** ArgoCD syncs sealed-secrets or any SealedSecret manifests.

---

## 🔁 Rotating the Certificate

To rotate the keypair:

```bash
rm -rf .sealedsecrets-keypair/
./generate-sealed-okta.sh <CLUSTER_NAME>
kubectl -n kube-system delete secret sealed-secrets-key
kubectl -n kube-system create secret tls sealed-secrets-key \
  --cert=.sealedsecrets-keypair/controller.crt \
  --key=.sealedsecrets-keypair/controller.key
```

Re-run the script to regenerate sealed secrets for each cluster.

---

## 🧾 Git Hygiene

### ✅ Commit:

- `controller.crt`
- `sealed-okta-*.yaml`

### ❌ DO NOT Commit:

- `controller.key`
- `/tmp/okta-unsealed-*.yaml`

Consider adding `.sealedsecrets-keypair/controller.key` to your `.gitignore`.

---

## ✅ Verification

After ArgoCD syncs the controller and SealedSecrets, confirm the secret exists:

```bash
kubectl get secret okta-sso-secret -n argocd -o yaml
```

---

## 📦 Notes

- If you're managing multiple clusters, each cluster may share the same cert for simplicity, or you can generate per-cluster keypairs.
- This method is ideal for **airgapped** or **pre-bootstrapped GitOps** workflows, where secrets must exist before Sealed Secrets is deployed.

---

## 🧰 Optional Improvements

- Auto-upload keypair to Kubernetes in the script
- Validate cluster readiness before sealing
- Encrypt other secrets (e.g. webhook tokens, SMTP, etc.) using the same flow

---

## 🛡️ Security

- Private keys must never be committed
- Consider rotating certs periodically and re-sealing all secrets
- Use separate certs per environment if strict separation is required

---
