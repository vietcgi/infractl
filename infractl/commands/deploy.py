"""Cluster Deployment Command.

This module provides commands for deploying and managing RKE2 clusters
using the new modular RKE2 implementation.
"""

import logging
import os
import sys
from pathlib import Path
from typing import Dict, Any, List, Optional

import typer
import yaml

from ..modules import get_ssh_pool
from ..modules.rke2.deploy import ClusterDeployment
from ..modules.rke2.models import Node

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger("deploy")

app = typer.Typer(help="Cluster deployment and management commands")


def create_node_objects(
    config: Dict[str, Any], ssh_user: str, ssh_key_path: str
) -> List[Node]:
    """Create Node objects from configuration.
    
    Args:
        config: Cluster configuration dictionary
        ssh_user: Default SSH username
        ssh_key_path: Path to SSH private key
        
    Returns:
        List of Node objects
    """
    nodes = []
    ssh_key_path = os.path.expanduser(ssh_key_path)

    # Process master nodes
    for idx, node_data in enumerate(config.get('masters', []), 1):
        node = Node(
            name=node_data.get('name', f'master-{idx}'),
            ip=node_data['ip'],
            role='master',
            ssh_user=node_data.get('ssh_user', ssh_user),
            ssh_key_path=node_data.get('ssh_key_path', ssh_key_path),
            labels=node_data.get('labels', {}),
            taints=node_data.get('taints', []),
        )
        nodes.append(node)

    # Process worker nodes
    for idx, node_data in enumerate(config.get('agents', []), 1):
        node = Node(
            name=node_data.get('name', f'worker-{idx}'),
            ip=node_data['ip'],
            role='worker',
            ssh_user=node_data.get('ssh_user', ssh_user),
            ssh_key_path=node_data.get('ssh_key_path', ssh_key_path),
            labels=node_data.get('labels', {}),
            taints=node_data.get('taints', []),
        )
        nodes.append(node)

    return nodes


def load_cluster_config(name: str, region: str, env: str) -> Dict[str, Any]:
    """Load and validate cluster configuration from the standard location.
    
    Args:
        name: Cluster name
        region: AWS region
        env: Environment (prod/stage/dev)
        
    Returns:
        Cluster configuration dictionary
        
    Raises:
        FileNotFoundError: If config file is not found
        ValueError: If config is invalid
    """
    possible_paths = [
        Path(f'clusters/rke2/{region}/{env}/{name}/cluster.yaml'),
        Path(f'clusters/{region}/{env}/{name}/cluster.yaml'),
        Path(f'{name}/cluster.yaml'),
        Path(name) if name.endswith(('.yaml', '.yml')) else None,
    ]

    config_path = next((p for p in possible_paths if p and p.exists()), None)

    if not config_path:
        paths_tried = ', '.join(str(p) for p in possible_paths if p)
        raise FileNotFoundError(f'Cluster config not found. Tried: {paths_tried}')

    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)

    if 'masters' not in config or not config['masters']:
        raise ValueError('Cluster config must contain at least one master node')

    return config


@app.command()
def cluster(
    name: str = typer.Option(..., '--name', '-n', help='Name of the cluster to deploy'),
    region: str = typer.Option('us-east', '--region', '-r', help='AWS region'),
    env: str = typer.Option('prod', '--env', '-e', help='Environment (prod/stage/dev)'),
    ssh_user: str = typer.Option('kevin', '--ssh-user', '-u', help='SSH username for node access'),
    ssh_key_path: str = typer.Option(
        '~/.ssh/id_rsa',
        '--ssh-key',
        help='Path to SSH private key',
    ),
    dry_run: bool = typer.Option(
        False, '--dry-run', help='Show what would be done without making changes'
    ),
    force: bool = typer.Option(
        False, '--force', '-f', help='Force deployment even if cluster exists'
    ),
    debug: bool = typer.Option(False, '--debug', help='Enable debug output'),
) -> int:
    """Deploy or update an RKE2 cluster.
    
    Example:
        python -m infractl.cli deploy cluster --name mycluster --region us-east --env prod
    """
    try:
        if debug:
            logging.getLogger().setLevel(logging.DEBUG)

        logger.info(f'🚀 Starting deployment of cluster: {name} in {region}/{env}')

        # Load and validate cluster configuration
        config = load_cluster_config(name, region, env)
        logger.debug('Loaded config: %s', config)

        # Create Node objects
        nodes = create_node_objects(config, ssh_user, ssh_key_path)
        logger.info(
            f'Discovered {len([n for n in nodes if n.role == "master"])} master(s) and '
            f'{len([n for n in nodes if n.role == "worker"])} worker(s)'
        )

        # Initialize deployment handler
        ssh_pool = get_ssh_pool()
        deployment = ClusterDeployment(ssh_pool, dry_run=dry_run)

        # Deploy the cluster
        result = deployment.deploy(name, region, env, nodes, force=force)
        if isinstance(result, dict):
            if not result.get('success', False):
                logger.error(f'❌ Failed to deploy cluster: {name}')
                logger.error(f'Errors: {result.get("errors", [])}')
                print("\n--- Deployment Error Details ---")
                print("Master results:", result.get('masters', {}))
                print("Worker results:", result.get('workers', {}))
                print("Health check:", result.get('health', {}))
                print("-------------------------------\n")
                return 1
            else:
                logger.info(f'✅ Successfully deployed cluster: {name}')
                print("\n--- Deployment Summary ---")
                print("Master results:", result.get('masters', {}))
                print("Worker results:", result.get('workers', {}))
                print("Health check:", result.get('health', {}))
                print("-------------------------\n")
                return 0
        else:
            # Fallback for legacy boolean return
            if result:
                logger.info(f'✅ Successfully deployed cluster: {name}')
                return 0
            logger.error(f'❌ Failed to deploy cluster: {name}')
            return 1

    except Exception as e:
        logger.error(f'❌ Deployment failed: {e}', exc_info=debug)
        return 1

if __name__ == "__main__":
    app()
