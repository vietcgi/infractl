"""RKE2 cluster deployment and management."""
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path
import os

from .models import Node
from .installer import RKE2Installer
from infractl.modules.ssh import ConnectionPool

logger = logging.getLogger("rke2.deploy")

class ClusterDeployment:
    """Handles RKE2 cluster deployment operations."""

    def __init__(self, connection_pool: ConnectionPool, dry_run: bool = False, force: bool = False):
        """Initialize the cluster deployment handler.
        
        Args:
            connection_pool: Connection pool for SSH connections
            dry_run: If True, only log commands without executing them
            force: If True, force deployment/reset
        """
        self.connection_pool = connection_pool
        self.dry_run = dry_run
        self.installer = RKE2Installer(connection_pool, dry_run=dry_run)
        self.force = force

    def deploy(
        self,
        name: str,
        region: str,
        env: str,
        nodes: List[Node],
        force: bool = False
    ) -> bool:
        """Deploy or update an RKE2 cluster.
        
        Args:
            name: Name of the cluster
            region: AWS region
            env: Environment (prod/stage/dev)
            nodes: List of nodes in the cluster
            force: Force deployment even if cluster exists
            
        Returns:
            bool: True if deployment was successful, False otherwise
        """
        try:
            master_nodes = [n for n in nodes if n.role == 'master']
            worker_nodes = [n for n in nodes if n.role == 'worker']
            
            if not master_nodes:
                raise ValueError("At least one master node is required")
            
            logger.info(
                f"Deploying cluster '{name}' in {region}/{env} with "
                f"{len(master_nodes)} master(s) and {len(worker_nodes)} worker(s)"
            )
            
            # If force is enabled, reset the cluster first
            if force:
                self._reset_cluster(nodes)
            
            # Use the new deploy_cluster function from the installer module
            from .installer.deployment import deploy_cluster
            
            # Deploy the cluster
            result = deploy_cluster(
                self.installer,
                master_nodes=master_nodes,
                worker_nodes=worker_nodes
            )
            
            if not result.get('success', False):
                logger.error(f"Cluster deployment failed: {result.get('message', 'Unknown error')}")
                return False
            
            logger.info(f"Successfully deployed cluster: {name}")
            return True
            
        except Exception as e:
            logger.error(f"Cluster deployment failed: {e}", exc_info=True)
            return False
    
    def _ensure_ssh_dir(self) -> None:
        """Ensure the .ssh/sockets directory exists."""
        import subprocess
        
        ssh_dir = os.path.expanduser('~/.ssh')
        sockets_dir = os.path.join(ssh_dir, 'sockets')
        
        if not os.path.exists(sockets_dir):
            os.makedirs(sockets_dir, mode=0o700, exist_ok=True)
            # Set restrictive permissions on the sockets directory
            os.chmod(sockets_dir, 0o700)
    
    def _run_ssh_command(self, node: Node, command: str, check: bool = True, timeout: int = 30) -> Tuple[bool, str]:
        """Run a single SSH command on a node using OpenSSH connection pooling."""
        import subprocess
        import shlex
        import time
        
        # Ensure the sockets directory exists
        self._ensure_ssh_dir()
        
        # Build the SSH command with connection pooling
        ssh_cmd = [
            'ssh',
            '-o', 'StrictHostKeyChecking=no',
            '-o', 'UserKnownHostsFile=/dev/null',
            '-o', 'LogLevel=ERROR',
            '-o', f'ConnectTimeout={min(10, timeout)}',
            '-o', 'ControlMaster=auto',
            '-o', 'ControlPath=~/.ssh/sockets/%r@%h:%p',
            '-o', 'ControlPersist=10m',
            '-i', node.ssh_key_path,
            f'{node.ssh_user}@{node.ip}',
            f'sudo bash -c {shlex.quote(command)}' if command.startswith('sudo ') else command
        ]
        
        start_time = time.time()
        try:
            result = subprocess.run(
                ssh_cmd,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            
            if result.returncode != 0 and check:
                error_msg = f"Command failed with status {result.returncode}: {result.stderr.strip()}"
                return False, error_msg
                
            return True, result.stdout.strip()
            
        except subprocess.TimeoutExpired:
            elapsed = time.time() - start_time
            return False, f"Command timed out after {elapsed:.1f}s"
            
        except Exception as e:
            return False, f"SSH command failed: {str(e)}"
    
    def _reset_node(self, node: Node, is_server: bool) -> Tuple[bool, str]:
        """Reset a single node."""
        import time
        
        start_time = time.time()
        role = 'server' if is_server else 'agent'
        service_name = f'rke2-{role}'
        
        def log_step(step: str, message: str):
            elapsed = time.time() - start_time
            logger.info(f'⏱️  [{node.name}] [{step}] {message} ({elapsed:.1f}s)')
        
        try:
            log_step('START', f'Starting reset of {role} node')
            
            # Step 1: Stop services
            log_step('STOP', 'Stopping services')
            for cmd in [
                f'sudo systemctl stop {service_name} || true',
                'sudo systemctl stop containerd || true'
            ]:
                success, output = self._run_ssh_command(node, cmd, check=False)
                if not success:
                    log_step('WARN', f'Failed to stop service: {output}')
            
            # Step 2: Run reset scripts if they exist
            for script in ['rke2-killall.sh', 'rke2-uninstall.sh']:
                log_step('SCRIPT', f'Checking for {script}')
                check_cmd = f'sudo test -x /usr/local/bin/{script} && echo exists || echo not_found'
                exists = self._run_ssh_command(node, check_cmd)[1].strip() == 'exists'
                
                if exists:
                    log_step('SCRIPT', f'Running {script}')
                    success, output = self._run_ssh_command(node, f'sudo /usr/local/bin/{script}', check=False)
                    if not success:
                        log_step('WARN', f'Script {script} failed: {output}')
            
            # Step 3: Clean up files and directories
            log_step('CLEANUP', 'Removing files')
            paths = [
                '/etc/systemd/system/rke2-*.service',
                '/etc/rancher/rke2',
                '/var/lib/rancher/rke2',
                '/var/lib/kubelet',
                '/usr/local/bin/rke2*',
                '/usr/local/bin/kubectl',
                '/usr/local/bin/crictl',
                '/usr/local/bin/ctr',
                '/var/lib/cni',
                '/var/run/cilium'
            ]
            
            for path in paths:
                self._run_ssh_command(node, f'sudo rm -rf {path} 2>/dev/null || true', check=False)
            
            # Step 4: Clean up network
            log_step('NETWORK', 'Cleaning up network')
            cmds = [
                'sudo iptables -F',
                'sudo iptables -t nat -F',
                'sudo iptables -t mangle -F',
                'sudo iptables -X',
                'sudo ipvsadm --clear',
                'sudo modprobe -r ipip || true',
                'sudo modprobe -r ip_vs || true',
                'sudo systemctl daemon-reload',
                'sudo systemctl reset-failed'
            ]
            
            for cmd in cmds:
                self._run_ssh_command(node, f'{cmd} 2>/dev/null || true', check=False)
            
            # Step 5: Kill remaining processes
            log_step('CLEANUP', 'Killing remaining processes')
            self._run_ssh_command(
                node,
                'sudo pkill -9 -f "rke2|kube|k3s|containerd|cni|flannel|cilium" 2>/dev/null || true',
                check=False
            )
            
            duration = time.time() - start_time
            log_step('SUCCESS', f'Reset completed in {duration:.1f} seconds')
            return True, f'Successfully reset node {node.name}'
            
        except Exception as e:
            duration = time.time() - start_time
            error_msg = f'Failed to reset node {node.name} after {duration:.1f}s: {str(e)}'
            logger.error(f'❌ {error_msg}', exc_info=True)
            return False, error_msg

    def _reset_cluster(self, nodes: List[Node]) -> None:
        """Reset all nodes in the cluster in parallel with maximum concurrency.
        
        This method uses a two-level parallelization approach:
        1. First level: Process multiple nodes in parallel
        2. Second level: Within each node, run operations in parallel
        
        Args:
            nodes: List of nodes to reset
        """
        if not nodes:
            logger.warning("No nodes to reset")
            return

        total_nodes = len(nodes)
        logger.info(f"🔄 Starting parallel reset of {total_nodes} nodes...")
        start_time = time.time()
        
        # Maximum number of parallel node resets - use min of 20 or 2x number of nodes
        max_node_workers = min(20, total_nodes * 2)
        
        # Track all futures with their corresponding node names
        future_to_node = {}
        
        # Use a single ThreadPoolExecutor for all parallel operations
        with ThreadPoolExecutor(max_workers=max_node_workers * 4, 
                              thread_name_prefix="node_reset") as executor:
            
            # Submit all node resets in parallel
            for node in nodes:
                is_server = node.role == 'master'
                future = executor.submit(
                    self._reset_node,
                    node,
                    is_server
                )
                future_to_node[future] = node.name
            
            # Process results as they complete
            completed = 0
            failed = 0
            
            for future in as_completed(future_to_node):
                node_name = future_to_node[future]
                completed += 1
                try:
                    success, message = future.result()
                    status = "✅" if success else "❌"
                    logger.info(f"[{completed}/{total_nodes}] {status} {node_name} ({(time.time() - start_time):.1f}s): {message}")
                    
                    if not success:
                        failed += 1
                        if not self.force:
                            # Cancel all pending futures if we're not forcing
                            for f in future_to_node:
                                if not f.done():
                                    f.cancel()
                            break
                            
                except Exception as e:
                    failed += 1
                    logger.error(f"❌ Error resetting node {node_name}: {str(e)}")
                    if not self.force:
                        # Cancel all pending futures if we're not forcing
                        for f in future_to_node:
                            if not f.done():
                                f.cancel()
                        break
            
            # Log completion
            duration = time.time() - start_time
            success_count = completed - failed
            
            logger.info(f"\n🚀 Reset completed in {duration:.1f} seconds")
            logger.info(f"✅ {success_count} nodes reset successfully")
            
            if failed > 0:
                logger.warning(f"❌ {failed} nodes failed to reset")
                if not self.force:
                    raise RuntimeError(f"Failed to reset {failed} nodes")
