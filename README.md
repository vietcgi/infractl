# RKE2 Multipass GitOps Platform

This is a full-featured GitOps bootstrap system for HA RKE2 clusters using:

- Multipass (for local clusters)
- ArgoCD (for GitOps deployment)
- Cert-Manager (for TLS)
- SealedSecrets (for secure secrets in Git)
- ApplicationSet (for multi-cluster app delivery)
- GitHub Actions (for CI validation)

## Setup

1. Configure your `cluster.yaml`
2. Run:

```bash
chmod +x bootstrap.sh
./bootstrap.sh
```

3. Validate configuration and secrets:

```bash
python3 scripts/validate-cluster.py clusters/cluster-a.yaml
./scripts/lint-ansible.sh
./scripts/seal-secret.sh -n argocd -f sealed-secrets/raw/argocd-admin-secret.yaml
```

4. Visit ArgoCD:
- https://argocd.emodo.com


## 🔄 Dynamic IP Handling (Multipass)

When using `mode: multipass`, IP addresses are not static. Each time you reboot or recreate a VM, the IP can change.

This system automatically handles dynamic IP changes:

- When you run `./bootstrap.sh clusters/dev/cluster.yaml`, it calls `generate-inventory.sh` internally.
- For each node with `mode: multipass`, the script runs:
  ```bash
  multipass info "$NAME" | awk '/IPv4/ {print $2}'
  ```
- This ensures the most current IP is detected and written to:
  ```
  ansible/hosts-<cluster>.ini
  ```

✅ Your Ansible runs and SSH will always target the right live IP.

To refresh just the inventory:
```bash
./scripts/generate-inventory.sh clusters/dev/cluster.yaml ansible/hosts-dev.ini
```

## 🛠 Troubleshooting Node Join Failures (e.g. master2 not joining)

### 🧯 Symptom
You may see repeated errors like:
```
failed to validate token: failed to get CA certs: Get "https://<ip>:9345/cacerts": dial tcp <ip>:9345: connect: connection refused
```

This means the node (e.g., master2) is unable to reach the primary server (`master1`) to join the cluster.

---

### ✅ Manual Recovery (Non-Destructive)

To fix a failed RKE2 server (like master2) without wiping the whole cluster:

1. **Stop and clean RKE2 on the broken node**:
```bash
multipass exec master2 -- sudo systemctl stop rke2-server
multipass exec master2 -- sudo rm -rf /etc/rancher /var/lib/rancher
```

2. **Re-provision only that node via Ansible**:
```bash
ansible-playbook -i ansible/hosts-dev.ini ansible/playbook.yml --limit master2
```

3. **Confirm the node joins the cluster**:
```bash
export KUBECONFIG=~/.kube/rke2.yaml
kubectl get nodes
```

---

### ⚠️ DO NOT run `CLEAN=true` unless you want to destroy the entire cluster.

That will delete all VMs, data, configs, and start from zero.

---

### 🧠 Pro Tip: Limit a node during full bootstrap (optional)
To re-provision a single node safely using bootstrap:
```bash
LIMIT=master2 ./bootstrap.sh clusters/dev/cluster.yaml
```

Then in your `run-ansible.sh`, modify:
```bash
ansible-playbook -i "$INVENTORY_FILE" ansible/playbook.yml --limit "$LIMIT"
```

This makes your system safe for partial repairs.


---

## ⚠️ Experimental: Docker Node Support (`mode: docker`)

You can define cluster nodes using `mode: docker`, which provisions lightweight RKE2 nodes inside privileged Docker containers.

### Example:
```yaml
workers:
  - name: docker-worker1
    mode: docker
```

### 🚫 Known Limitations:
- No systemd (unless simulated)
- etcd is unreliable inside containers
- Networking is not production-like
- No support for CSI drivers or real NIC-level load balancing
- Containers must run in `--privileged` mode

### ✅ Use Cases:
- CI testing (RKE2 installs, Ansible logic)
- Simulating ephemeral edge nodes
- Fast cluster teardown & reset for dev

**Docker mode is disabled by default.**
Use with caution. It is NOT suitable for HA, CNI, or persistent workloads.


---

## 🧠 How to Use This GitOps Bootstrap Repo

### 🔧 Adding a New Cluster
1. Create a new file under `clusters/<env>/<cluster-name>.yaml`.
2. Include fields: `cluster`, `url`, `name`, `region`, `labels`, etc.
3. Run:
   ```bash
   ./scripts/generate-inventory.sh
   ./scripts/run-ansible.sh <env>
   ```

### 🔄 Updating System Apps
- Edit YAMLs under `apps-repo/system/` (e.g. Prometheus, SealedSecrets).
- Commit changes to Git.
- ArgoCD will auto-sync and apply.

### 🧪 Validating Apps
- Run:
  ```bash
  ./scripts/validate-cluster.py
  ./scripts/health-check.sh
  ```
- Or use GitHub Actions validation workflow on PR.

### 🔐 Managing Secrets
- Place unsealed secrets in `sealed-secrets/raw/`
- Seal with:
  ```bash
  kubeseal --controller-name=sealed-secrets --controller-namespace=kube-system --format yaml < raw/secret.yaml > sealed.yaml
  ```
- Commit the sealed file under `sealed-secrets/`.

### 👥 RBAC and Access Control
- Edit `manifests/argocd-rbac-cm.yaml` to manage user roles
- Grant access via email or Okta group match

### 🚀 Bootstrapping a New Cluster
```bash
./bootstrap.sh
```
This installs ArgoCD and applies ApplicationSets.


---

## 🔁 Detecting Manual Changes (Drift Detection)

ArgoCD should be the **sole source of truth**. To detect manual changes made with `kubectl apply`:

### 1. Enable Auto-Sync in Application YAMLs
Make sure every ArgoCD Application has:
```yaml
syncPolicy:
  automated:
    prune: true
    selfHeal: true
```

### 2. Detect Drift via ArgoCD CLI
```bash
argocd app list
argocd app diff <app-name>
```

### 3. Monitor Drift in Logs
```bash
kubectl -n argocd logs deployment/argocd-repo-server | grep 'live state differs'
```

### 4. Visual Detection
Use ArgoCD UI:
- Apps with yellow ⚠️ or red ❌ are out of sync
- Click "Diff" to see what's changed

### 5. Optional: Alert on Drift
- Enable Prometheus metrics
- Alert on:
  - `argocd_app_info{sync_status="OutOfSync"}`
  - `argocd_app_sync_total`

> Tip: You can also use Slack/Webhook alerts from ArgoCD to notify on drift or sync failures.
