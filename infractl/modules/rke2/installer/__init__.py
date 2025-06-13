"""RKE2 installation and management.

This package provides a modular approach to RKE2 cluster installation and management.
It's organized into several focused modules:

- core: Core installation logic
- configuration: Cluster and node configuration
- service: Service management
- verification: Health checks and verification
- deployment: Cluster deployment orchestration
- models: Data models and types
- utils: Utility functions
"""

from .core import RKE2Installer
from .configuration import generate_node_config, write_node_config
from .service import start_service, stop_service, restart_service, install_rke2
from .verification import verify_installation, wait_for_ready
from .deployment import deploy_cluster, check_cluster_health
from .models import Node, NodeRole, DeploymentState, ClusterConfig, DeploymentPhase
from .utils import generate_token, write_yaml_file, read_yaml_file, merge_dicts, parse_kubectl_output, validate_node

__all__ = [
    'RKE2Installer',
    'generate_node_config',
    'write_node_config',
    'start_service',
    'stop_service',
    'restart_service',
    'install_rke2',
    'verify_installation',
    'wait_for_ready',
    'deploy_cluster',
    'check_cluster_health',
    'Node',
    'NodeRole',
    'DeploymentState',
    'ClusterConfig',
    'DeploymentPhase',
    'generate_token',
    'write_yaml_file',
    'read_yaml_file',
    'merge_dicts',
    'parse_kubectl_output',
    'validate_node',
]
