# RKE2 Cluster Management Module

This module provides a Python-based solution for deploying and managing RKE2 (Rancher Kubernetes Engine 2) clusters at scale. It's designed to be reliable, efficient, and easy to use for managing Kubernetes clusters in production environments.

## Features

- 🚀 **Automated Cluster Deployment**: Deploy RKE2 clusters with minimal configuration
- 🔄 **High Availability**: Support for HA control planes with etcd clustering
- ⚡ **Efficient**: Uses connection pooling and parallel operations for fast deployments
- 🔍 **Health Monitoring**: Built-in health checks for cluster components
- 🔒 **Security**: Secure by default with proper authentication and encryption
- 📊 **Observability**: Comprehensive logging and metrics collection
- 🛠️ **Extensible**: Modular design for easy extension and customization

## Installation

```bash
# Navigate to the project root
cd /Users/kevin/emodo/infra

# Install in development mode
pip install -e .

# Or add to your requirements.txt
-e .
```

## Quick Start

```python
from rke2 import Node, ConnectionPool, RKE2Installer

# Define your nodes
master_nodes = [
    Node(name="master-1", ip="192.168.1.10", role="master"),
    Node(name="master-2", ip="192.168.1.11", role="master"),
]

worker_nodes = [
    Node(name="worker-1", ip="192.168.1.20", role="worker"),
    Node(name="worker-2", ip="192.168.1.21", role="worker"),
]

# Set up connection pool
connection_pool = ConnectionPool(max_connections=50)

# Create installer instance
installer = RKE2Installer(connection_pool)

# Deploy the cluster
results = installer.deploy_cluster(
    master_nodes=master_nodes,
    worker_nodes=worker_nodes
)

# Check results
if results['success']:
    print("Cluster deployed successfully!")
    
    # Get kubeconfig
    kubeconfig = installer.get_kubeconfig(master_nodes[0])
    with open("kubeconfig.yaml", "w") as f:
        f.write(kubeconfig)
else:
    print("Cluster deployment failed:")
    for error in results.get('errors', []):
        print(f"- {error}")

# Clean up
connection_pool.close_all()
```

## Architecture

```
rke2/
├── __init__.py          # Module exports and version
├── connection.py        # SSH connection pooling
├── health.py           # Cluster health checks
├── installer.py        # Core installation logic
├── models.py           # Data models
├── utils.py            # Utility functions
└── README.md           # This file
```

## Configuration

### Node Configuration

```python
from rke2 import Node

# Basic node
node = Node(
    name="master-1",
    ip="192.168.1.10",
    role="master",  # or 'worker'
    ssh_user="root",
    ssh_key_path="~/.ssh/id_rsa",
    labels={"environment": "production"},
    taints=[{"key": "dedicated", "value": "gpu", "effect": "NoSchedule"}]
)
```

### Connection Pooling

The `ConnectionPool` class manages SSH connections efficiently:

```python
from rke2 import ConnectionPool

# Create a connection pool with max 100 connections
connection_pool = ConnectionPool(max_connections=100)
```

## Advanced Usage

### Custom Installation

```python
# Install and configure RKE2 on a single node
success = installer.install_rke2(node, role="master")
if success:
    installer.configure_node(node, master_nodes)
    installer.start_rke2(node, role="master")
```

### Health Checks

```python
# Check cluster health
health = check_cluster_health(installer, master_nodes[0])
print(f"Cluster healthy: {health.get('healthy', False)}")

# Wait for control plane to be ready
if wait_for_control_plane_ready(installer, master_nodes[0], timeout=300):
    print("Control plane is ready!")
```

## Error Handling

The module raises appropriate exceptions for error conditions. Always use try/except blocks:

```python
try:
    results = installer.deploy_cluster(master_nodes, worker_nodes)
except Exception as e:
    print(f"Deployment failed: {str(e)}")
    # Handle error
```

## Logging

Configure logging to see detailed output:

```python
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
```

## Best Practices

1. **Use Connection Pooling**: Always reuse the same `ConnectionPool` instance
2. **Handle Cleanup**: Call `connection_pool.close_all()` when done
3. **Validate Inputs**: Use the provided validation functions
4. **Monitor Health**: Regularly check cluster health
5. **Secure Credentials**: Use proper SSH key management

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests
5. Submit a pull request

## License

[Your License Here]

## Support

For issues and feature requests, please open an issue on GitHub.
