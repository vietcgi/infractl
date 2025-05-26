# e-gitops Platform Documentation

A production-ready, GitOps-first RKE2 platform built for multi-cluster, multi-app, and multi-cloud deployment using Kubernetes-native best practices.

---

## 📘 Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Cluster Bootstrap](#cluster-bootstrap)
4. [System Apps via GitOps](#system-apps-via-gitops)
5. [Application Delivery](#application-delivery)
6. [TLS with Cert-Manager](#tls-with-cert-manager)
7. [Secrets Management](#secrets-management)
8. [Monitoring and Logs](#monitoring-and-logs)
9. [Cluster Registration](#cluster-registration)
10. [GitHub Actions + Validation](#github-actions--validation)
11. [Maintenance & Recovery](#maintenance--recovery)
12. [Troubleshooting](#troubleshooting)
13. [Extending e-gitops](#extending-e-gitops)

---

## 🧭 Overview

`e-gitops` is a declarative Kubernetes platform powered by:
- **RKE2 HA Clusters**
- **ArgoCD GitOps**
- **Cert-Manager for TLS**
- **SealedSecrets for encryption**
- **ApplicationSet for multi-cluster app delivery**
- **Prometheus + Grafana for monitoring**
- **Longhorn for persistent volumes**

---

## 🏗 Architecture

```text
Git ───> ArgoCD ───> RKE2 Clusters
       ↳ System Apps (via apps-repo/system/*)
       ↳ Dev Apps (via apps-repo/cluster-a/*)
             ↳ ApplicationSet discovers apps
             ↳ TLS via Cert-Manager + Ingress
             ↳ Secrets via SealedSecrets
             ↳ Monitoring via Prometheus/Grafana
```

---

## 🚀 Cluster Bootstrap

1. Configure `clusters/cluster-a.yaml`
2. Run:

```bash
./bootstrap.sh --cluster clusters/cluster-a.yaml
```

3. Validate before running:

```bash
python3 scripts/validate-cluster.py clusters/cluster-a.yaml
./scripts/lint-ansible.sh
```

---

## 📦 System Apps via GitOps

All system apps live under `apps-repo/system/`:
- `argocd`
- `cert-manager`
- `sealed-secrets`
- `ingress-nginx`
- `longhorn`
- `prometheus`

These are synced by `ApplicationSet` defined in `apps-repo/applicationset-system.yaml`.

---

## 🚀 Application Delivery

- Each cluster has a folder in `apps-repo/cluster-a/`
- ArgoCD ApplicationSet syncs apps per-cluster
- All apps use Helm or Kustomize

---

## 🔐 TLS with Cert-Manager

- TLS via Let’s Encrypt ClusterIssuer
- Applied via ArgoCD
- Ingress annotations used for automation

---

## 🛡️ Secrets Management

- Use `scripts/seal-secret.sh` to encrypt secrets
- Sealed secrets are safe to commit to Git
- Applied via ArgoCD in any app or system folder

---

## 📊 Monitoring and Logs

- Prometheus + Grafana via `kube-prometheus-stack`
- Deployed in `monitoring` namespace
- Grafana default: `https://grafana.emodo.com` (`admin/admin`)
- Optional: Loki for logs

---

## 🔁 Cluster Registration

- ArgoCD detects `argocd.argoproj.io/secret-type: cluster`
- Enables multi-cluster sync from central controller

---

## ✅ GitHub Actions + Validation

- Validates `cluster.yaml`:
  - schema
  - duplicate IPs
  - hostnames
  - subnet overlaps
- Lints Ansible configs
- Enforced pre-bootstrap

---

## 🧯 Maintenance & Recovery

| Task                      | Command                            |
|---------------------------|-------------------------------------|
| Re-run cluster bootstrap  | `./bootstrap.sh`                   |
| Update admin secret       | Edit raw YAML → re-seal            |
| Recover TLS               | Reapply ClusterIssuer + certs      |

---

## 🧩 Troubleshooting

- **TLS cert not issued**: Check ingress class, ClusterIssuer
- **ArgoCD access denied**: Check RBAC in `argocd-rbac-cm.yaml`
- **Bootstrap fails**: Run validation + check VM status

---

## 🚀 Extending e-gitops

- Add new system app to `apps-repo/system/<app>`
- Add new cluster by creating new `cluster-<name>.yaml`
- Add dev workloads to `apps-repo/cluster-<name>/`

You're now operating at GitOps elite level 🎯
