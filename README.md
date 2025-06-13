# RKE2 Cluster Management

A Python-based tool for managing RKE2 clusters with Ansible-based bootstrap and ArgoCD GitOps workflows.

## Features

- **Baremetal Management**: Deploy and manage baremetal servers using MAAS (Metal as a Service)
- **Kubernetes Bootstrap**: Automated RKE2 cluster provisioning using Ansible
- **GitOps Workflow**: Application deployment and management via ArgoCD
- **Infrastructure as Code**: Define cluster and application configurations in YAML
- **Multi-Environment**: Support for multiple regions and environments (prod, staging, dev)

## Prerequisites

- Python 3.7+ for the control machine
- Ansible 2.9+ for cluster provisioning
- MAAS server access (for baremetal deployments)
- SSH access to target servers
- kubectl for cluster interaction
- ArgoCD CLI (optional, for application management)

## Installation

1. Clone the repository and install dependencies:
   ```bash
   git clone <repository-url>
   cd infractl
   
   # Create and activate virtual environment
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   
   # Install Python dependencies
   pip install -e .
   
   # Install Ansible dependencies
   pip install ansible
   
   # Install ArgoCD CLI (macOS)
   brew install argocd
   ```

2. Configure environment variables in `.env`:
   ```bash
   # MAAS Configuration
   MAAS_URL=http://your-maas-server:5240/MAAS/api/2.0
   MAAS_API_KEY=your-api-key
   
   # SSH Configuration
   SSH_USER=your-ssh-user
   SSH_KEY_PATH=~/.ssh/id_rsa
   
   # Kubernetes Configuration
   KUBECONFIG=~/.kube/config
   ```

## Cluster Lifecycle Management

### 1. Bootstrap Kubernetes Cluster

```bash
# Create inventory from MAAS
python -m infractl.cli inventory generate <cluster-name> \
  --region <region> --env <environment>

# Bootstrap RKE2 cluster using Ansible
ansible-playbook -i ansible/inventory/ ansible/bootstrap-rke2.yml \
  -e "cluster_name=<cluster-name>"
```

### 2. Deploy Applications with ArgoCD

```bash
# Get ArgoCD admin password
kubectl -n argocd get secret argocd-initial-admin-secret \
  -o jsonpath="{.data.password}" | base64 -d

# Login to ArgoCD
argocd login <argocd-server-address> \
  --username admin \
  --password <password>

# Deploy applications
argocd app create <app-name> \
  --repo <git-repo-url> \
  --path <path-to-manifests> \
  --dest-namespace <namespace> \
  --dest-server <cluster-url>
```

## Cluster Operations

### Scale Nodes

```bash
# Update cluster configuration
python -m infractl.cli scale <cluster-name> \
  --region <region> --env <environment> \
  --worker-count <new-count>

# Apply changes with Ansible
ansible-playbook -i ansible/inventory/ ansible/scale-rke2.yml
```

### Upgrade Cluster

```bash
# Update cluster configuration with new RKE2 version
python -m infractl.cli upgrade <cluster-name> \
  --region <region> --env <environment> \
  --version <rke2-version>

# Run upgrade playbook
ansible-playbook -i ansible/inventory/ ansible/upgrade-rke2.yml
```

## 🖥️ Reinstall Cluster Nodes

Reinstall one or more nodes in a cluster with the specified OS and kernel. This operation is useful for OS upgrades, kernel updates, or recovering problematic nodes.

### Prerequisites

- MAAS API access with appropriate permissions
- Non-root SSH user with sudo privileges on target nodes
- SSH key-based authentication configured
- Puppet master access (for certificate cleanup)

### Basic Usage

```bash
# Reinstall all nodes in the cluster
infractl reinstall cluster <cluster-name> \
  --region <region> --env <environment> \
  --os <ubuntu-release> --kernel <hwe-kernel> \
  --ssh-user <your-username> \
  --ssh-key-path ~/.ssh/id_rsa \
  --yes

# Reinstall specific nodes
infractl reinstall cluster <cluster-name> \
  --region <region> --env <environment> \
  --server host1 --server host2 \
  --os noble --kernel ga-24.04 \
  --ssh-user <your-username>

# Dry run (show what would be done without making changes)
infractl reinstall cluster <cluster-name> --dry-run
```

### Key Options

- `--os`: Ubuntu release to install (e.g., 'noble', 'jammy')
- `--kernel`: HWE kernel version (e.g., 'ga-24.04', 'hwe-24.04')
- `--server`: Specific server(s) to reinstall (can be specified multiple times)
- `--ssh-user`: Non-root SSH username (required)
- `--ssh-key-path`: Path to SSH private key (default: ~/.ssh/id_rsa)
- `--parallel`: Number of servers to reinstall in parallel (default: 3, 0 for unlimited)
- `--timeout`: Timeout in seconds to wait for each server (default: 900s)
- `--skip-puppet-cleanup`: Skip Puppet certificate cleanup (not recommended)
- `--yes`: Skip confirmation prompt
- `--dry-run`: Show what would be done without making changes

### Process Overview

1. **Pre-flight Checks**
   - Verify MAAS connectivity
   - Validate SSH access
   - Check server status in MAAS

2. **Node Reinstallation**
   - Release node in MAAS
   - Deploy specified OS and kernel
   - Wait for deployment to complete (up to 15 minutes timeout)
   - Verify network connectivity

3. **Post-Installation**
   - Clean up Puppet certificates (unless skipped)
   - Wait for server to come back online
   - Verify SSH access

### Parallel Execution

```bash
# Reinstall all servers with up to 4 in parallel
infractl reinstall cluster my-cluster --parallel 4 --yes

# Let the script determine optimal concurrency
infractl reinstall cluster my-cluster --parallel 0 --yes
```

### Troubleshooting

- **SSH Connection Issues**: Ensure your SSH key is properly configured on the target nodes
- **Deployment Timeouts**: Check MAAS logs and server console for errors
- **Puppet Certificate Issues**: Use `--skip-puppet-cleanup` if needed, but clean up manually later
- **Network Problems**: Verify VLAN and network configuration in MAAS

### Example Output

```
🔍 DRY RUN: Would reinstall 3 servers in cluster my-cluster
   • host1 (status: Ready)
   • host2 (status: Ready)
   • host3 (status: Ready)

✅ Successfully reinstalled 3/3 servers
```

### Parallel Execution

When reinstalling multiple servers, you can use the `--parallel` flag to control concurrency:

```bash
# Reinstall all servers with up to 4 in parallel
python -m infractl.cli reinstall cluster my-cluster --parallel 4 --yes

# Let the script determine optimal concurrency (one worker per server)
python -m infractl.cli reinstall cluster my-cluster --parallel 0 --yes
```

**Note**: Parallel execution can significantly reduce total reinstallation time for large clusters.

## 🔄 ArgoCD App Management

### Trigger Sync

```bash
python -m infractl.cli sync --app my-app
```

### Check App Status

```bash
python -m infractl.cli status --app my-app
```

### Auto-Sync by Label

```bash
python -m infractl.cli autosync --namespace argocd --label auto-sync=on
```

### Generate Summary Report

```bash
python -m infractl.cli summary [--namespace argocd] [--export json|csv]
```

### Auto-Repair Drifted/Degraded Apps

```bash
python -m infractl.cli autorepair --namespace argocd
```

## 🗂 Cluster Lifecycle Management

### Register New Cluster

```bash
python -m infractl.cli cluster register --file clusters/dev/cluster.yaml
```

### List Registered Clusters

```bash
python -m infractl.cli cluster list
```

### View Cluster Details

```bash
python -m infractl.cli cluster info <cluster-name>
```

### Delete Cluster

```bash
python -m infractl.cli cluster delete <cluster-name> --confirm
```

### Backup Cluster State

```bash
python -m infractl.cli cluster backup <cluster-name> --output backup/
```

## Configuration

Cluster configurations follow this structure:

```
clusters/
  └── <region>/
      └── <environment>/
          └── <cluster-name>/
              ├── cluster.yaml      # Cluster specification
              ├── inventory.ini     # Generated inventory
              └── group_vars/       # Ansible variables
                  ├── all.yml
                  ├── master.yml
                  └── worker.yml
```

## Development

1. Install development dependencies:
   ```bash
   pip install -e ".[dev]"
   ```

2. Run tests:
   ```bash
   # Run unit tests
   pytest tests/unit
   
   # Run integration tests (requires test environment)
   pytest tests/integration
   ```

3. Code quality:
   ```bash
   # Format code
   black .
   
   # Lint code
   flake8
   
   # Type checking
   mypy .
   
   # Security scanning
   bandit -r infractl/
   ```

4. Documentation:
   ```bash
   # Generate API documentation
   pdoc --html -o docs/ infractl/
   ```

## 🖥️ Baremetal Cluster Reinstallation

This project includes a command-line tool for reinstalling servers in a baremetal cluster managed by MAAS (Metal as a Service).

### Prerequisites

- Access to MAAS server with API credentials
- SSH access to the Puppet master
- Properly configured cluster YAML files
- Python 3.7+ with required dependencies

### Usage

#### Reinstall a Single Server

```bash
python -m infractl.cli reinstall reinstall-cluster <cluster_name> \
  --region <region> --env <environment> \
  --server <hostname> \
  --os <distro_series> --kernel <hwe_kernel>
```

Example:
```bash
python -m infractl.cli reinstall reinstall-cluster dc11a \
  --region us-east --env prod \
  --server boss-mullet \
  --os noble --kernel ga-24.04
```

#### Reinstall All Servers in a Cluster

Omit the `--server` flag to reinstall all servers:

```bash
python -m infractl.cli reinstall reinstall-cluster dc11a \
  --region us-east --env prod \
  --os noble --kernel ga-24.04
```

#### Options

- `--os`: OS distribution series (e.g., 'noble' for Ubuntu 24.04)
- `--kernel`: HWE kernel version (e.g., 'ga-24.04')
- `--ssh-user`: Username for SSH access to Puppet master (default: from SSH_USER env var)
- `--ssh-key`: Path to SSH private key (default: from SSH_KEY_PATH env var or ~/.ssh/id_rsa)
- `--skip-puppet-clean`: Skip Puppet certificate cleanup (not recommended)
- `--yes`: Skip confirmation prompt (for automation)

### Workflow

1. **MAAS Connection**:
   - Connects to the MAAS API using credentials from environment variables
   - Verifies API access and permissions

2. **Server Processing**:
   - For each target server:
     - Retrieves server details from MAAS
     - Releases the server from current deployment
     - Cleans up Puppet certificate (if not skipped)
     - Redeploys with specified OS and kernel
     - Monitors deployment status

3. **Completion**:
   - Reports success/failure for each server
   - Provides summary of operations

### Error Handling

- Gracefully handles connection issues
- Provides detailed error messages for troubleshooting
- Validates input parameters before execution
- Maintains idempotency where possible

### Logging

- Detailed logging of all operations
- Progress indicators for long-running tasks
- Color-coded output for better readability
- Option to increase verbosity with `--verbose` flag

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
