# 🛠️ Operational Handbook: ArgoCD GitOps Platform

This document outlines key operational procedures and best practices for running and maintaining the ArgoCD GitOps platform.

---

## ✅ Daily Operations

### 🔄 Syncing Applications

- Applications sync automatically via `syncPolicy: automated`.
- To force a manual sync (if needed):
  ```bash
  argocd app sync <app-name>
  ```

### 🔍 Monitoring Application Health

- Use ArgoCD UI or CLI:
  ```bash
  argocd app list
  argocd app get <app-name>
  ```

- Look for `OutOfSync` or `Degraded` status in CLI or ArgoCD UI.

---

## 🔔 Notifications

- Notifications are sent via **Postmark SMTP** on:
  - Sync failures
  - Health degradation

- Managed in:
  ```
  apps/system/argocd-notifications/configmap.yaml
  apps/system/argocd-notifications/secret.yaml
  ```

---

## 📦 Secrets Management

- All Kubernetes secrets are encrypted using **SealedSecrets**.
- Raw secrets must never be committed to Git.
- Sealed secrets are stored in:
  ```
  sealed-secrets/*.yaml
  ```

- To seal a new secret:
  ```bash
  kubectl create secret generic my-secret --from-literal=password=supersecure --dry-run=client -o yaml > raw.yaml
  kubeseal --scope strict --format yaml < raw.yaml > sealed.yaml
  ```

---

## 🔐 Access Control (RBAC)

- Access is enforced via Okta groups and AppProjects.
- Default policy is readonly.
- Refer to [docs/RBAC.md](./RBAC.md) for group-to-role mappings.

---

## 📊 Observability

- Prometheus is deployed for metrics.
- Grafana dashboards can be extended under:
  ```
  apps/system/grafana/
  ```

- Recommended dashboards:
  - ArgoCD App Health (ID: 14584)
  - ArgoCD Sync/Drift Status (ID: 14585)

---

## 🧯 Incident Response

### 🧼 Reset Admin Password (only if enabled)
```bash
htpasswd -bnBC 10 "" "new-password" | tr -d ':
'
kubectl patch secret argocd-secret -n argocd --patch '{"stringData":{"admin.password":"<bcrypt>","admin.passwordMtime":"'"$(date +%FT%T%Z)"'"}}'
```

### 🚫 Disable Admin User (Best Practice)
```bash
kubectl patch configmap argocd-cm -n argocd --type merge -p '{"data":{"admin.enabled":"false"}}'
kubectl rollout restart deployment argocd-server -n argocd
```

---

## 🔁 Backup & Restore

- Backup SealedSecrets key:
  ```bash
  kubectl get secret -n kube-system sealed-secrets-key -o yaml > backup/sealed-secrets-key.yaml
  ```

- Documented in [docs/BACKUP.md](./BACKUP.md)

---

## 📁 Structure Overview

```
apps/                      # All ArgoCD applications
clusters/                  # Per-environment cluster definitions
projects/                  # AppProject configs
sealed-secrets/            # Sealed Kubernetes secrets
scripts/                   # Bootstrap and utilities
docs/                      # Operational documentation
```

---

## 📋 To-Do for Ops

- [ ] Review ArgoCD sync statuses daily
- [ ] Rotate sealed secrets if keys are rotated
- [ ] Audit Okta group mappings quarterly
- [ ] Review alert coverage for all critical apps