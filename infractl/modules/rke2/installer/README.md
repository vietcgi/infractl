# RKE2 Installer

A modular and extensible RKE2 cluster installer and manager.

## Features

- **Modular Design**: Split into focused modules for better maintainability
- **Idempotent Operations**: Safe to run multiple times
- **Concurrent Deployments**: Deploy multiple nodes in parallel
- **Comprehensive Logging**: Detailed logs for debugging and auditing
- **Health Checks**: Built-in verification of cluster health
- **Configuration Management**: Flexible configuration system
- **Service Management**: Start, stop, and restart RKE2 services

## Installation

```bash
# Install from source
pip install -e .

# Or install in development mode with all dependencies
pip install -e ".[dev]"
```

## Usage

### Python API

```python
from rke2.installer import (
    Node, NodeRole, ClusterConfig, 
    deploy_cluster, check_cluster_health
)

# Define nodes
master_nodes = [
    Node(
        name="master-1",
        ip="10.0.0.1",
        role=NodeRole.MASTER,
        user="root",
        ssh_key_path="/path/to/ssh_key"
    )
]

worker_nodes = [
    Node(
        name="worker-1",
        ip="10.0.0.2",
        role=NodeRole.WORKER,
        user="root",
        ssh_key_path="/path/to/ssh_key"
    )
]

# Configure the cluster
config = ClusterConfig(
    cluster_name="my-cluster",
    tls_san=["10.0.0.1", "my-cluster.example.com"]
)

# Deploy the cluster
success = deploy_cluster(
    master_nodes=master_nodes,
    worker_nodes=worker_nodes,
    config=config,
    reset_nodes=True,
    wait_timeout=600
)

# Check cluster health
if success:
    health = check_cluster_health(master_nodes)
    print(f"Cluster is {'healthy' if health.is_healthy else 'unhealthy'}")
```

### Command Line Interface

```bash
# Install RKE2 on nodes
rke2-installer install \
  --masters user@master1 user@master2 \
  --workers user@worker1 user@worker2 \
  --ssh-key ~/.ssh/id_rsa \
  --cluster-name my-cluster

# Check cluster health
rke2-installer check --master user@master1 --ssh-key ~/.ssh/id_rsa
```

## Architecture

The installer is organized into several modules:

- **core.py**: Core installation logic
- **configuration.py**: Cluster and node configuration
- **service.py**: Service management (start/stop/restart)
- **verification.py**: Health checks and verification
- **deployment.py**: Cluster deployment orchestration
- **models.py**: Data models and types
- **utils.py**: Utility functions

## Development

### Running Tests

```bash
pytest tests/
```

### Linting and Formatting

```bash
# Format code with black and isort
black .
isort .

# Check for type errors
mypy .
# Check for style issues
flake8
```

## License

MIT
