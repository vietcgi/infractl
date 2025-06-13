
import typer
import sys
import os
import logging
import traceback
from pathlib import Path
import yaml
from typing import Dict, Any, Optional, Tuple
from infractl.modules import provision_multipass, install_rke2
from infractl.modules.install_rke2_scalable import RKE2Installer as ScalableRKE2Installer
from infractl.modules.ssh import get_ssh_pool
from infractl.modules.rke2.reset import RKE2Reset, reset_rke2_node
from infractl.modules.rke2.models import Node

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = typer.Typer()

def load_cluster_config(name: str, region: str, env: str) -> Dict[str, Any]:
    """Load cluster configuration from the standard location."""
    try:
        config_path = Path(f"clusters/rke2/{region}/{env}/{name}/cluster.yaml")
        logger.info(f"Loading cluster config from: {config_path}")
        
        if not config_path.exists():
            raise FileNotFoundError(f"Cluster config not found at {config_path}")
        
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
        
        logger.debug(f"Loaded config: {config}")
        
        # Ensure the config has the required structure
        if not isinstance(config, dict):
            raise ValueError(f"Invalid cluster config format: expected dict, got {type(config)}")
            
        if 'masters' not in config or not config.get('masters'):
            raise ValueError("Cluster config must contain at least one master node")
        
        return config
    except Exception as e:
        logger.error(f"Failed to load cluster config: {e}", exc_info=True)
        raise

@app.command("cluster")
def reset_cluster_cmd(
    name: str = typer.Option(..., "--name", "-n", help="Cluster name"),
    region: str = typer.Option("us-east", "--region", "-r", help="Cluster region"),
    env: str = typer.Option("prod", "--env", "-e", help="Cluster environment (prod/stage/dev)"),
    ssh_user: str = typer.Option("kevin", "--ssh-user", "-u", help="SSH username for node access"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be reset without making changes"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation prompt"),
):
    """
    Reset an RKE2 cluster by uninstalling RKE2 from all nodes.
    
    For production environments, uses direct SSH to reset nodes.
    For non-production environments, uses multipass.
    """
    try:
        if env.lower() == 'prod':
            # For production, use RKE2Installer
            typer.echo(f"🔁 Resetting production cluster: {name} in {region}/{env}")
            
            # Load cluster config
            config = load_cluster_config(name, region, env)
            
            # Update SSH user in node configurations
            for node_type in ['masters', 'agents']:
                for node in config.get(node_type, []):
                    node['ssh_user'] = ssh_user
            
            if not force and not dry_run:
                typer.confirm(
                    f"⚠️  This will uninstall RKE2 from all nodes in production cluster {name}. Continue?",
                    abort=True
                )
            
            # Initialize SSH connection pool
            ssh_pool = get_ssh_pool()
            
            # Create nodes from config
            nodes = []
            for node_type in ['masters', 'agents']:
                for node_config in config.get(node_type, []):
                    node = Node(
                        name=node_config.get('name', ''),
                        ip=node_config['ip'],
                        role='master' if node_type == 'masters' else 'worker',
                        ssh_user=node_config.get('ssh_user', ssh_user),
                        ssh_key_path=node_config.get('ssh_key_path', '~/.ssh/id_rsa'),
                        labels=node_config.get('labels', {}),
                        taints=node_config.get('taints', [])
                    )
                    nodes.append(node)
            
            from concurrent.futures import ThreadPoolExecutor, as_completed
            import time
            
            def reset_single_node(node):
                import threading
                try:
                    thread_name = threading.current_thread().name
                    start_time = time.time()
                    logger.info(f"[Thread-{thread_name}] 🚀 Starting reset of {node.name} ({node.ip})...")
                    typer.echo(f"🔄 Starting reset of {node.name} ({node.ip})...")
                    
                    # Log when we're about to call reset_rke2_node
                    logger.info(f"[Thread-{thread_name}] Calling reset_rke2_node for {node.name}")
                    reset_result = reset_rke2_node(ssh_pool, node, is_server=(node.role == 'master'))
                    
                    duration = time.time() - start_time
                    logger.info(f"[Thread-{thread_name}] ✅ Completed reset of {node.name} in {duration:.1f}s")
                    return (True, f"✅ Successfully reset {node.name} in {duration:.1f}s", node)
                except Exception as e:
                    logger.error(f"[Thread-{thread_name}] ❌ Failed to reset {node.name}: {e}", exc_info=True)
                    return (False, f"❌ Failed to reset {node.name}: {e}", node)
            
            # Process nodes in parallel with a max of 5 concurrent operations
            max_workers = min(5, len(nodes))  # Don't use too many workers to avoid overloading the system
            successful = 0
            failed = 0
            
            logger.info(f"Starting parallel reset of {len(nodes)} nodes with {max_workers} workers")
            logger.info(f"Thread pool executor will use {max_workers} workers")
            
            logger.info("Creating ThreadPoolExecutor...")
            with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix='NodeReset') as executor:
                # Start all reset operations
                future_to_node = {}
                for node in nodes:
                    try:
                        logger.info(f"🚀 Submitting reset task for node: {node.name} ({node.ip})")
                        future = executor.submit(reset_single_node, node)
                        future_to_node[future] = node
                        logger.info(f"✅ Submitted reset task for node: {node.name} (Future: {future})")
                    except Exception as e:
                        logger.error(f"❌ Failed to submit task for node {node.name}: {e}", exc_info=True)
                        failed += 1
                
                # Process results as they complete
                for future in as_completed(future_to_node):
                    node = future_to_node[future]
                    try:
                        success, message, node_result = future.result()
                        typer.echo(message)
                        if success:
                            successful += 1
                            logger.info(f"Successfully reset node: {node.name}")
                        else:
                            failed += 1
                            logger.error(f"Failed to reset node {node.name}")
                    except Exception as e:
                        error_msg = f"Unexpected error processing {node.name}: {str(e)}\n{traceback.format_exc()}"
                        typer.echo(f"❌ {error_msg}", err=True)
                        logger.error(error_msg, exc_info=True)
                        failed += 1
                        
            typer.echo(f"\nReset completed: {successful} successful, {failed} failed")
            
            typer.echo(f"\n✅ Successfully reset production cluster: {name}")
            typer.echo("\nTo deploy the cluster, run:")
            typer.echo(f"  infractl deploy cluster --name {name} --region {region} --env {env}")
            
        else:
            # For non-production, use multipass
            typer.echo(f"🔁 Resetting development cluster {name} in {region}/{env}")
            provision_multipass.provision(name=name, refresh_only=True)
            install_rke2.create_cluster(
                name=name,
                region=region,
                env=env,
                skip_argocd=True,  # Skip ArgoCD by default for resets
                install_flux=False,
                force_refresh_ips=True,
            )
            
    except Exception as e:
        error_msg = f"❌ Reset failed: {str(e)}\n{traceback.format_exc()}" if '--debug' in sys.argv else f"❌ Reset failed: {e}"
        typer.echo(error_msg, err=True)
        logger.error("Reset failed", exc_info=True)
        if '--debug' in sys.argv:
            raise
        sys.exit(1)
