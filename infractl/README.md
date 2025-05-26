
# 🚀 infractl

**infractl** is a full-featured DevOps CLI and API toolkit for managing Kubernetes clusters and GitOps workflows — with native support for ArgoCD, Ansible, Slack alerts, and auto-healing.

---

## 📦 Installation

```bash
pip install -e .
```

---

## 🧠 CLI Usage (Typer)

### 🔧 General CLI

```bash
python infractl/cli.py --help
```

### 🚀 Bootstrap ArgoCD

```bash
python infractl/cli.py bootstrap --cluster <cluster.yaml> [--clean]
```

### 🔍 Diagnose Components

```bash
python infractl/cli.py diagnose --component argocd
```

### 🧪 Validate Cluster Config

```bash
python infractl/cli.py validate --file clusters/dev/cluster.yaml
```

### 🩺 Run Cluster Doctor

```bash
python infractl/cli.py doctor
```

---

## 🔁 ArgoCD App Management

### Trigger Sync

```bash
python infractl/cli.py sync --app my-app
```

### App Status

```bash
python infractl/cli.py status --app my-app
```

### Auto-Sync by Label

```bash
python infractl/cli.py autosync --namespace argocd --label auto-sync=on
```

### Summary Report

```bash
python infractl/cli.py summary [--namespace argocd] [--export json|csv]
```

### Auto-Repair Drifted/Degraded Apps

```bash
python infractl/cli.py autorepair --namespace argocd
```

---

## 🗂 Cluster Lifecycle Management

### Register New Cluster

```bash
python infractl/cli.py cluster register --file clusters/dev/cluster.yaml
```

### List Registered Clusters

```bash
python infractl/cli.py cluster list
```

### View Cluster Details

```bash
python infractl/cli.py cluster get --name dev-cluster
```

### Deregister a Cluster

```bash
python infractl/cli.py cluster deregister --name dev-cluster
```

### Reapply GitOps Apps

```bash
python infractl/cli.py cluster reapply --name dev-cluster
```

---

## 🔐 API Access (Optional)

Use FastAPI at `/api/main.py` for remote control:
- Protected via `X-API-Key`
- Slack alerts
- JSON-based endpoints for all CLI features

---

## 📄 Config Files

### `.env.example`
```env
INFRACTL_API_KEY=infractl-secret
INFRACTL_SLACK_WEBHOOK=https://hooks.slack.com/services/...
```

### `cluster.yaml` Example
```yaml
name: dev-cluster
kubeconfig: /kubeconfigs/dev.yaml
inventory: ansible/hosts-dev.ini
apps:
  - apps/dev/applicationset.yaml
  - apps/dev/monitoring.yaml
```

---

## 🛠️ Requirements

- Python 3.10+
- kubectl configured
- access to target cluster + Ansible inventory

