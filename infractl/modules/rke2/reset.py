"""RKE2 reset and cleanup functionality."""
import logging
import os
import shlex
import time
from typing import List, Tuple, Optional, Dict, Any

from infractl.modules.ssh import ConnectionPool
from .models import Node

logger = logging.getLogger(__name__)

class RKE2Reset:
    """Handles RKE2 reset and cleanup operations."""
    
    def __init__(self, connection_pool: ConnectionPool):
        """Initialize the RKE2 reset handler.
        
        Args:
            connection_pool: Connection pool for SSH connections
        """
        self.connection_pool = connection_pool
    
    def _ensure_ssh_dir(self) -> None:
        """Ensure the .ssh/sockets directory exists."""
        ssh_dir = os.path.expanduser('~/.ssh')
        sockets_dir = os.path.join(ssh_dir, 'sockets')
        
        if not os.path.exists(sockets_dir):
            os.makedirs(sockets_dir, mode=0o700, exist_ok=True)
            # Set restrictive permissions on the sockets directory
            os.chmod(sockets_dir, 0o700)
    
    def _ssh_exec(self, node: Node, command: str, check: bool = True, timeout: int = 120) -> Tuple[int, str, str]:
        """Execute a command on the remote node using OpenSSH connection pooling.
        
        Args:
            node: The node to execute the command on
            command: The command to execute
            check: If True, raise an exception if the command fails
            timeout: Command timeout in seconds
            
        Returns:
            If check is True: str - The command output
            If check is False: Tuple[int, str, str] - (exit_code, stdout, stderr)
            
        Raises:
            RuntimeError: If command fails and check is True
        """
        import subprocess
        import shlex
        import time
        
        start_time = time.time()
        
        # Ensure the sockets directory exists with proper permissions
        self._ensure_ssh_dir()
        
        # Use ControlMaster for connection reuse
        control_path = os.path.expanduser('~/.ssh/sockets/%r@%h:%p')
        
        # Build the base SSH command with connection pooling
        ssh_base = [
            'ssh',
            '-o', 'StrictHostKeyChecking=no',
            '-o', 'UserKnownHostsFile=/dev/null',
            '-o', 'LogLevel=ERROR',
            '-o', f'ConnectTimeout={min(10, timeout)}',
            '-o', 'ControlMaster=auto',
            '-o', f'ControlPath={control_path}',
            '-o', 'ControlPersist=10m',
            '-o', 'ServerAliveInterval=15',
            '-o', 'ServerAliveCountMax=3',
            '-o', 'BatchMode=yes',
            '-o', 'Compression=yes',  # Enable compression for faster transfers
            '-o', 'IPQoS=throughput',  # Optimize for throughput
            '-i', node.ssh_key_path
        ]
        
        # Quote the command properly for the remote shell
        if command.startswith('sudo '):
            # For sudo commands, we need to quote the entire command
            quoted_cmd = f'timeout {timeout} bash -c {shlex.quote(command)}'
        else:
            quoted_cmd = command
        
        # Build the final command
        ssh_cmd = ssh_base + [f'{node.ssh_user}@{node.ip}', quoted_cmd]
        
        command_id = f"{node.name}:[{command[:30]}{'...' if len(command) > 30 else ''}]"
        logger.debug(f"[SSH] Starting command {command_id}")
        
        try:
            # Set up process with pipes for stdout/stderr
            start_exec = time.time()
            process = subprocess.Popen(
                ssh_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,  # Line buffered
                universal_newlines=True
            )
            
            # Wait for process to complete with timeout
            try:
                stdout, stderr = process.communicate(timeout=timeout)
                returncode = process.returncode
            except subprocess.TimeoutExpired:
                process.kill()
                stdout, stderr = process.communicate()
                raise
                
            exec_time = time.time() - start_exec
            duration = time.time() - start_time
            
            # Process the results
            if returncode != 0 and check:
                error_msg = f"Command failed with status {returncode} after {duration:.2f}s (exec: {exec_time:.2f}s)"
                if stderr.strip():
                    error_msg += f"\n{stderr.strip()}"
                logger.error(f"[SSH] {error_msg}")
                raise RuntimeError(error_msg)
            
            logger.debug(f"[SSH] Completed {command_id} in {duration:.2f}s (exec: {exec_time:.2f}s)")
            
            if check:
                return stdout.strip()
                
            return returncode, stdout.strip(), stderr.strip()
            
        except subprocess.TimeoutExpired:
            duration = time.time() - start_time
            error_msg = f"Command {command_id} timed out after {duration:.1f}s"
            logger.error(f"[SSH] {error_msg}")
            raise RuntimeError(error_msg)
            
        except Exception as e:
            duration = time.time() - start_time
            error_msg = f"SSH command {command_id} failed after {duration:.1f}s: {str(e)}"
            logger.error(f"[SSH] {error_msg}", exc_info=True)
            raise RuntimeError(error_msg) from e
            logger.debug(f"[SSH] Command execution took {elapsed:.2f}s")
    
    def monitor_logs(self, node: Node, service_name: str, duration: int = 30):
        """Monitor RKE2 service logs in the background.
        
        Args:
            node: The node to monitor
            service_name: Name of the service to monitor (rke2-server or rke2-agent)
            duration: How long to monitor logs in seconds
        """
        try:
            log_file = os.path.join('logs', f"{node.name}-reset.log")
            os.makedirs(os.path.dirname(log_file), exist_ok=True)
            
            def _monitor():
                try:
                    with open(log_file, 'a') as f:
                        f.write(f"=== Starting log monitoring for {service_name} ===\n")
                    
                    # Use timeout command to limit the duration
                    cmd = f"timeout {duration} sudo journalctl -u {service_name} -n 100 -f"
                    exit_code, stdout, stderr = self._ssh_exec(node, cmd, check=False)
                    
                    # Write the collected logs to file
                    if stdout:
                        with open(log_file, 'a') as f:
                            f.write(stdout)
                    if stderr:
                        with open(log_file, 'a') as f:
                            f.write(f"\n=== ERROR ===\n{stderr}\n")
                            
                    with open(log_file, 'a') as f:
                        f.write(f"\n=== Log monitoring completed ===\n")
                        
                except Exception as e:
                    logger.error(f"Error in log monitor for {node.name}: {str(e)}")
            
            import threading
            monitor_thread = threading.Thread(target=_monitor, daemon=True)
            monitor_thread.start()
            return monitor_thread
            
        except Exception as e:
            logger.error(f"Failed to start log monitor for {node.name}: {str(e)}")
            return None
    
    def _run_rke2_script(self, node: Node, script_name: str, log_prefix: str = '') -> bool:
        """Run an RKE2 script if it exists.
        
        Args:
            node: The node to run the script on
            script_name: Name of the script to run
            log_prefix: Prefix for log messages
            
        Returns:
            bool: True if script was found and executed, False otherwise
        """
        script_path = f"/usr/local/bin/{script_name}"
        logger.info(f'{log_prefix}🔍  Looking for {script_path}...')
        
        try:
            # First try to run the script directly with sudo
            logger.info(f'{log_prefix}  🔫 Attempting to run {script_path}...')
            result = self._ssh_exec(
                node, 
                f'sudo {script_path} 2>&1 || echo "SCRIPT_NOT_FOUND"', 
                check=False, 
                timeout=120
            )
            
            # Check if the script was not found
            if len(result) >= 2 and 'SCRIPT_NOT_FOUND' in result[1]:
                logger.info(f'{log_prefix}  ℹ️  {script_path} not found, skipping')
                return False
                
            # Script executed, log the output
            output = result[1][:500] + '...' if result[1] else 'No output'
            logger.info(f'{log_prefix}  ✅ {script_path} completed with output: {output}')
            return True
                
        except Exception as e:
            logger.error(f'{log_prefix}  ❌ Error running {script_path}: {str(e)}')
            return False

    def reset_node(self, node: Node, is_server: bool = True, reinstall: bool = True) -> bool:
        """Reset RKE2 on a single node.
        
        This method is optimized for parallel execution and uses OpenSSH connection pooling.
        It performs the following steps:
        1. Runs rke2-killall.sh if it exists
        2. Runs rke2-uninstall.sh if it exists
        3. Cleans up any remaining files and processes
        4. Optionally reinstalls RKE2
        
        Args:
            node: The node to reset
            is_server: Whether this is a server node
            reinstall: Whether to reinstall RKE2 after cleanup
            
        Returns:
            bool: True if reset was successful, False otherwise
        """
        import time
        from concurrent.futures import ThreadPoolExecutor, as_completed
        
        role = 'server' if is_server else 'agent'
        service_name = f'rke2-{role}'
        start_time = time.time()
        
        # Set up logging
        log_file = os.path.join('logs', f'rke2_reset_{node.name}.log')
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        
        # Configure file handler
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging.DEBUG)
        file_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        file_handler.setFormatter(file_formatter)
        
        # Add file handler to logger
        logger.addHandler(file_handler)
        
        def log_step(step: str, message: str):
            """Helper to log each step with timing"""
            elapsed = time.time() - start_time
            logger.info(f'⏱️  [{step}] {message} on {node.name} ({elapsed:.1f}s)')
               
        def run_commands_parallel(commands: List[str], step: str, check: bool = False, timeout: int = 30):
            """Run multiple commands in parallel with optimized concurrency.
            
            Args:
                commands: List of commands to execute
                step: Step name for logging
                check: Whether to raise an exception if any command fails
                timeout: Timeout in seconds for each command
            """
            if not commands:
                return
                
            start_time = time.time()
            log_step(step, f'Starting {len(commands)} commands')
            
            # Group commands by type to optimize parallel execution
            command_groups = {}
            for cmd in commands:
                cmd_type = 'file_ops' if 'rm -rf' in cmd else 'system_ops'
                command_groups.setdefault(cmd_type, []).append(cmd)
            
            # Process each group with appropriate concurrency
            for group_name, group_commands in command_groups.items():
                group_start = time.time()
                logger.debug(f"[PARALLEL] Starting group '{group_name}' with {len(group_commands)} commands")
                
                # Use more workers for file operations which are typically I/O bound
                max_workers = min(20, len(group_commands) + 4) if group_name == 'file_ops' else min(10, len(group_commands) + 2)
                
                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    # Submit all commands in this group
                    future_to_cmd = {}
                    for cmd in group_commands:
                        safe_cmd = f'timeout {timeout} bash -c {shlex.quote(cmd)} 2>/dev/null || true'
                        future = executor.submit(
                            self._ssh_exec,
                            node=node,
                            command=safe_cmd,
                            check=check,
                            timeout=timeout
                        )
                        future_to_cmd[future] = cmd
                    
                    # Process results as they complete
                    for future in as_completed(future_to_cmd):
                        cmd = future_to_cmd[future]
                        try:
                            future.result()
                        except Exception as e:
                            logger.warning(f"Command failed: {cmd} - {str(e)}")
                            if check:
                                raise
                
                group_duration = time.time() - group_start
                logger.debug(f"[PARALLEL] Completed group '{group_name}' in {group_duration:.2f}s")
            
            total_duration = time.time() - start_time
            log_step(step, f'Completed {len(commands)} commands in {total_duration:.1f}s')
        
        try:
            logger.info(f'🧹 Resetting RKE2 {role} on {node.name} ({node.ip})')
            logger.info(f'🔧 Using SSH user: {node.ssh_user}, key: {node.ssh_key_path}')
            
            # Step 1: Run rke2-killall.sh if it exists
            log_step('KILLALL', 'Running rke2-killall.sh')
            self._run_rke2_script(node, 'rke2-killall.sh', '1️⃣')
            
            # Step 2: Run rke2-uninstall.sh if it exists
            log_step('UNINSTALL', 'Running rke2-uninstall.sh')
            self._run_rke2_script(node, 'rke2-uninstall.sh', '2️⃣')
            
            # Step 3: Stop and disable services in parallel
            service_commands = [
                f'systemctl stop {service_name}',
                f'systemctl disable {service_name}',
                'systemctl stop containerd',
                'systemctl disable containerd',
                'systemctl daemon-reload',
                'systemctl reset-failed'
            ]
            run_commands_parallel(service_commands, 'SERVICES')
            
            # Step 4: Optimized file and directory cleanup using find and xargs for better performance
            cleanup_commands = [
                # Systemd service files
                'sudo find /etc/systemd/system -name "rke2-*" -delete',
                
                # Main RKE2 directories
                'sudo rm -rf /etc/rancher/rke2',
                'sudo rm -rf /var/lib/rancher/rke2',
                'sudo rm -rf /var/lib/kubelet',
                
                # Binaries
                'sudo find /usr/local/bin -name "rke2*" -delete',
                'sudo rm -f /usr/local/bin/kubectl /usr/local/bin/crictl /usr/local/bin/ctr',
                
                # Network and runtime directories
                'sudo rm -rf /var/lib/cni /var/run/cilium /etc/cni/net.d',
                'sudo rm -rf /var/run/flannel /var/run/cni /var/run/containerd',
                'sudo rm -rf /var/run/kubelet /var/run/kubernetes /var/run/rke2',
                
                # Clean up etcd and rancher state
                'sudo rm -rf /var/lib/etcd /var/lib/rancher/state /var/lib/rancher/k3s',
                
                # Clean up kubelet data
                'sudo find /var/lib/kubelet -mindepth 1 -delete',
                
                # Clean up rancher agent and management state
                'sudo rm -rf /var/lib/rancher/agent /var/lib/rancher/credentialprovider',
                'sudo rm -rf /var/lib/rancher/management-state',
                
                # Clean up remaining RKE2 data
                'sudo rm -rf /var/lib/rancher/rke2/agent/containerd/*',
                'sudo rm -rf /var/lib/rancher/rke2/data/*',
                'sudo rm -rf /var/lib/rancher/rke2/server/cred/*',
                'sudo rm -rf /var/lib/rancher/rke2/server/db/*',
                'sudo rm -f /var/lib/rancher/rke2/server/tls/* /var/lib/rancher/rke2/server/token'
            ]
            
            # Group commands to reduce SSH connections
            run_commands_parallel(cleanup_commands, 'CLEANUP')
            
            # Step 5: Run network cleanup and iptables in parallel
            log_step('NETWORK', 'Starting parallel network cleanup')
            
            # Create a thread pool for parallel execution
            with ThreadPoolExecutor(max_workers=2) as executor:
                # Submit network cleanup as a background task
                network_future = executor.submit(self._cleanup_network, node)
                
                # Submit iptables cleanup as another background task
                iptables_future = executor.submit(
                    run_commands_parallel,
                    [
                        'iptables -F',
                        'iptables -t nat -F',
                        'iptables -t mangle -F',
                        'iptables -X',
                        'iptables -t nat -X',
                        'iptables -t mangle -X',
                        'ipvsadm --clear',
                        'modprobe -r ipip',
                        'modprobe -r ip_vs',
                        'modprobe -r ip_vs_rr',
                        'modprobe -r ip_vs_wrr',
                        'modprobe -r ip_vs_sh',
                        'modprobe -r nf_conntrack_ipv4',
                        'modprobe -r nf_conntrack_ipv6',
                        'modprobe -r xt_conntrack',
                        'modprobe -r nf_conntrack',
                        'ip link delete cni0',
                        'ip link delete flannel.1',
                        'ip link delete cilium_net',
                        'ip link delete cilium_host',
                        'ip route flush table main',
                        'ip -6 route flush table main',
                        'ip -4 rule flush',
                        'ip -6 rule flush',
                        'ip -4 route flush cache',
                        'ip -6 route flush cache',
                        'sysctl -w net.ipv4.ip_forward=0',
                        'sysctl -w net.ipv6.conf.all.forwarding=0',
                        'sysctl -w net.bridge.bridge-nf-call-iptables=0',
                        'sysctl -w net.bridge.bridge-nf-call-ip6tables=0'
                    ],
                    'IPTABLES'
                )
                
                # Wait for both tasks to complete
                network_future.result()
                iptables_future.result()
                
            log_step('NETWORK', 'Parallel network cleanup completed')
            
            # Step 7: Kill any remaining processes
            log_step('PROCESSES', 'Killing remaining processes')
            self._ssh_exec(
                node,
                'sudo pkill -9 -f "rke2|kube|k3s|containerd|cni|flannel|cilium" 2>/dev/null || true',
                check=False,
                timeout=30
            )
            
            # Reinstall if requested
            if reinstall:
                log_step('REINSTALL', 'Starting RKE2 reinstallation')
                try:
                    # Download and install RKE2
                    self._ssh_exec(
                        node,
                        'curl -sfL https://get.rke2.io | sudo sh -',
                        check=True,
                        timeout=300  # 5 minutes for download and install
                    )
                    
                    # Re-enable the service
                    self._ssh_exec(
                        node,
                        f'sudo systemctl enable {service_name}',
                        check=True,
                        timeout=30
                    )
                    
                    # Verify installation
                    result = self._ssh_exec(
                        node,
                        'command -v rke2 2>/dev/null || echo "not_found"',
                        check=True,
                        timeout=30
                    )
                    
                    if 'not_found' in (result[1] or ''):
                        logger.error(f'❌ RKE2 installation verification failed on {node.name}')
                        return False
                        
                    log_step('SUCCESS', 'RKE2 reset and reinstallation completed')
                    return True
                    
                except Exception as e:
                    log_step('ERROR', f'Failed to reinstall RKE2: {str(e)}')
                    return False
                
            return True
            
        except Exception as e:
            logger.error(f'❌ Unexpected error during reset on {node.name}: {str(e)}', exc_info=True)
            return False
            
        finally:
            # Clean up file handler
            file_handler.close()
            logger.removeHandler(file_handler)
        
        try:
            # Start log monitoring in background
            log_step('START', 'Starting log monitoring')
            monitor_thread = self.monitor_logs(node, service_name, duration=300)  # Monitor for 5 minutes
            
            try:
                # Step 1: Run rke2-killall.sh if it exists
                log_step('KILLALL', 'Running rke2-killall.sh')
                self._run_rke2_script(node, 'rke2-killall.sh', '1️⃣')
                
                # Step 2: Run rke2-uninstall.sh if it exists
                log_step('UNINSTALL', 'Running rke2-uninstall.sh')
                self._run_rke2_script(node, 'rke2-uninstall.sh', '2️⃣')
                
                # Clean up any remaining service files
                log_step('CLEANUP', 'Starting cleanup phase')
                
                # Stop and disable services
                log_step('SERVICES', 'Stopping and disabling services')
                for cmd in [
                    f'sudo systemctl stop {service_name}',
                    f'sudo systemctl disable {service_name}',
                    'sudo systemctl stop containerd',
                    'sudo systemctl disable containerd'
                ]:
                    self._ssh_exec(node, f'{cmd} 2>/dev/null || true', check=False, timeout=30)
                
                # Remove service files
                log_step('FILES', 'Removing service files')
                for path in [
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
                ]:
                    self._ssh_exec(node, f'sudo rm -rf {path} 2>/dev/null || true', check=False, timeout=30)
                
                # Clean up network
                log_step('NETWORK', 'Cleaning up network interfaces')
                self._cleanup_network(node)
                
                # Clean up iptables
                log_step('IPTABLES', 'Cleaning up iptables')
                for cmd in [
                    'sudo iptables -F',
                    'sudo iptables -t nat -F',
                    'sudo iptables -t mangle -F',
                    'sudo iptables -X',
                    'sudo ipvsadm --clear',
                    'sudo modprobe -r ipip',
                    'sudo modprobe -r ip_vs'
                ]:
                    self._ssh_exec(node, f'{cmd} 2>/dev/null || true', check=False, timeout=30)
                
                # Reload systemd
                log_step('SYSTEMD', 'Reloading systemd')
                for cmd in [
                    'sudo systemctl daemon-reload',
                    'sudo systemctl reset-failed'
                ]:
                    self._ssh_exec(node, f'{cmd} 2>/dev/null || true', check=False, timeout=30)
                
                # Kill any remaining processes
                log_step('PROCESSES', 'Killing remaining processes')
                self._ssh_exec(
                    node,
                    'sudo pkill -9 -f "rke2|kube|k3s|containerd|cni|flannel|cilium" 2>/dev/null || true',
                    check=False,
                    timeout=30
                )
                
                # Reinstall if requested
                if reinstall:
                    log_step('REINSTALL', f'Starting RKE2 reinstallation on {node.name}')
                    
                    # Prepare installation script
                    install_script = """
                    # Function to run commands with retries
                    run_with_retry() {
                        local cmd="$1"
                        local max_attempts=3
                        local delay=5
                        
                        for ((i=1; i<=max_attempts; i++)); do
                            echo "[Attempt $i/$max_attempts] Running: $cmd"
                            if eval "$cmd"; then
                                return 0
                            fi
                            echo "Command failed, retrying in ${delay}s..."
                            sleep $delay
                        done
                        echo "Command failed after $max_attempts attempts"
                        return 1
                    }
                    
                    set -e
                    
                    # Install RKE2 with retries
                    INSTALL_CMD='curl -sfL https://get.rke2.io | INSTALL_RKE2_CHANNEL=stable sh -s -'
                    if [ '{is_server}' = 'True' ]; then
                        INSTALL_CMD+=' server --cluster-init'
                    fi
                    
                    run_with_retry "$INSTALL_CMD"
                    
                    # Enable and start the service
                    SERVICE_NAME='rke2-server'
                    if [ '{is_server}' != 'True' ]; then
                        SERVICE_NAME='rke2-agent'
                    fi
                    
                    run_with_retry "systemctl enable $SERVICE_NAME"
                    run_with_retry "systemctl start $SERVICE_NAME"
                    
                    # Verify installation
                    if ! command -v rke2 >/dev/null 2>&1; then
                        echo "ERROR: RKE2 installation failed - rke2 command not found"
                        exit 1
                    fi
                    
                    # Verify service status
                    if ! systemctl is-active --quiet $SERVICE_NAME; then
                        echo "ERROR: RKE2 service is not active"
                        systemctl status $SERVICE_NAME || true
                        exit 1
                    fi
                    
                    # For server nodes, wait for cluster to be ready
                    if [ '{is_server}' = 'True' ]; then
                        echo "Waiting for RKE2 server to be ready..."
                        
                        # Wait for kubeconfig to be available
                        KUBECONFIG="/etc/rancher/rke2/rke2.yaml"
                        for i in $(seq 1 30); do
                            if [ -f "$KUBECONFIG" ]; then
                                break
                            fi
                            if [ $i -eq 30 ]; then
                                echo "ERROR: Timeout waiting for kubeconfig"
                                exit 1
                            fi
                            sleep 2
                        done
                        
                        # Wait for nodes to be ready
                        for i in $(seq 1 30); do
                            if /var/lib/rancher/rke2/bin/kubectl --kubeconfig="$KUBECONFIG" get nodes 2>/dev/null | grep -q Ready; then
                                echo "RKE2 server is ready"
                                exit 0
                            fi
                            echo "Waiting for RKE2 server to be ready ($i/30)..."
                            sleep 5
                        done
                        
                        echo "ERROR: Timeout waiting for RKE2 server to be ready"
                        /var/lib/rancher/rke2/bin/kubectl --kubeconfig="$KUBECONFIG" get nodes || true
                        exit 1
                    fi
                    
                    echo "RKE2 installation completed successfully"
                    """.format(is_server=str(is_server))
                    
                    # Execute the installation script
                    self._ssh_exec(
                        node,
                        f'sudo bash -c {shlex.quote(install_script)}',
                        check=True,
                        timeout=600  # 10 minutes for installation (with retries)
                    )
                    
                    logger.info(f"✅ RKE2 reinstalled successfully on {node.name}")
                    
                    # For server nodes, verify cluster status
                    if is_server:
                        logger.info(f"✅ RKE2 server is ready on {node.name}")
                    else:
                        logger.info(f"✅ RKE2 agent is running on {node.name}")
                    
                return True
                
            except Exception as e:
                log_step('ERROR', f'Reset failed: {str(e)}')
                return False
                
            finally:
                # Ensure log monitor is stopped
                if monitor_thread and monitor_thread.is_alive():
                    monitor_thread.join(timeout=5)
                
                # If we reach here and reinstall is False, log success
                if not reinstall:
                    logger.info(f'✅ RKE2 reset completed successfully on {node.name} (no reinstall)')
                return True
                    
        except Exception as e:
            logger.error(f'❌ Unexpected error during reset on {node.name}: {str(e)}')
            return False
    
    def _cleanup_network(self, node: Node) -> None:
        """Clean up RKE2/CNI network interfaces and routes safely.
        
        This method is designed to be safe and only removes RKE2/CNI specific
        interfaces and routes, leaving the system networking intact.
        """
        logger.info("🧹 Cleaning up RKE2/CNI network interfaces and routes")
        start_time = time.time()
        
        try:
            # Define the network cleanup script with safety checks
            network_cleanup_script = """
            # Function to run commands with error handling
            run_cmd() {
                local cmd="$1"
                local desc="$2"
                echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting: $desc"
                if ! eval "$cmd"; then
                    echo "[WARNING] Command failed (continuing): $cmd"
                    return 1
                fi
                return 0
            }
            
            # Set error handling to continue on error
            set +e
            
            # 1. Clean up CNI interfaces (only those created by RKE2/CNI)
            echo "[INFO] Cleaning up CNI interfaces..."
            for iface in $(ip -o link show | awk -F': ' '{print $2}' | 
                         grep -E r'(^cni[0-9]+$|^veth[0-9a-f]{8,10}@if|^cali[0-9a-f]{40}|^vxlan\.calico$|^tunl0$|^flannel\.[0-9]+$|^cilium_|^lxc[0-9]+$|^kube-ipvs0$|^antrea-|^gw[0-9a-f]+)' | 
                         grep -v -E '^(lo|eth[0-9]+|en[ops][0-9]+|bond[0-9]+|vlan[0-9]+|br[0-9]+|docker[0-9]+|virbr[0-9]+|vnet[0-9]+)'); do
                echo "Removing interface: $iface"
                ip link delete $iface 2>/dev/null || true
            done
            
            # 2. Clean up iptables rules specific to Kubernetes/RKE2
            echo "[INFO] Cleaning up Kubernetes iptables rules..."
            for table in filter nat mangle; do
                # Delete chains created by Kubernetes
                for chain in $(sudo iptables -t $table -L -n | grep -E '^Chain (KUBE-|CNI-|CALI-|ANTREA-|FLANNEL-|CILIUM-)' | awk '{print $2}'); do
                    echo "Flushing and removing chain $chain in table $table"
                    iptables -t $table -F $chain 2>/dev/null || true
                    iptables -t $table -X $chain 2>/dev/null || true
                done
                
                # Delete rules referencing Kubernetes
                iptables -t $table -S | grep -E 'KUBE-|CNI-|CALI-|ANTREA-|FLANNEL-|CILIUM-' | \
                while read -r rule; do
                    # Convert rule to deletion command
                    del_cmd=$(echo "$rule" | sed 's/^-A/-D/')
                    echo "Removing iptables rule: $del_cmd"
                    iptables -t $table $del_cmd 2>/dev/null || true
                done
            done
            
            # 3. Clean up IPVS (if used)
            if command -v ipvsadm >/dev/null 2>&1; then
                echo "[INFO] Cleaning up IPVS configuration..."
                ipvsadm --clear 2>/dev/null || true
            fi
            
            # 4. Clean up network namespaces (only those created by Kubernetes)
            echo "[INFO] Cleaning up network namespaces..."
            for ns in $(ip netns list 2>/dev/null | awk '{print $1}'); do
                # Only delete namespaces that look like they're from Kubernetes
                if [[ "$ns" =~ ^(cni-|k8s_|kube-|calico-|antrea-|cilium-) ]]; then
                    echo "Deleting network namespace: $ns"
                    ip netns delete "$ns" 2>/dev/null || true
                fi
            done
            
            # 5. Clean up conntrack entries (only for Kubernetes services)
            if command -v conntrack >/dev/null 2>&1; then
                echo "[INFO] Cleaning up conntrack entries..."
                # Only delete conntrack entries for Kubernetes services
                conntrack -L -n --proto tcp --dport 30000:32767 2>/dev/null | \
                grep -E 'dport=(30000|80|443|6443|2379|2380|10250|10251|10252|10255|10256|9099|9100|9153)' | \
                while read -r conn; do
                    # Extract conntrack entry details
                    proto=$(echo "$conn" | awk '{print $1}' | tr '[:upper:]' '[:lower:]')
                    src=$(echo "$conn" | grep -oP 'src=\K[^ ]+')
                    dst=$(echo "$conn" | grep -oP 'dst=\K[^ ]+')
                    sport=$(echo "$conn" | grep -oP 'sport=\K[^ ]+')
                    dport=$(echo "$conn" | grep -oP 'dport=\K[^ ]+')
                    
                    if [ -n "$src" ] && [ -n "$dst" ] && [ -n "$sport" ] && [ -n "$dport" ]; then
                        echo "Deleting conntrack entry: $src:$sport -> $dst:$dport $proto"
                        conntrack -D -p "$proto" -s "$src" -d "$dst" --sport "$sport" --dport "$dport" 2>/dev/null || true
                    fi
                done
            fi
            
            # 6. Clean up any remaining CNI config
            echo "[INFO] Cleaning up CNI config..."
            rm -f /etc/cni/net.d/* 2>/dev/null || true
            
            # 7. Restart networking services if available
            if systemctl list-unit-files | grep -q '\.service' | grep -q network; then
                echo "[INFO] Restarting network services..."
                systemctl restart networking 2>/dev/null || \
                systemctl restart NetworkManager 2>/dev/null || \
                systemctl restart systemd-networkd 2>/dev/null || true
            fi
            
            echo "[$(date '+%Y-%m-%d %H:%M:%S')] Network cleanup completed"
            """
            
            # Execute the network cleanup script with a timeout
            self._ssh_exec(
                node,
                f'sudo bash -c {shlex.quote(network_cleanup_script)}',
                check=False,
                timeout=300  # 5 minutes for network cleanup
            )
            
            logger.info(f"✅ Network cleanup completed in {time.time() - start_time:.1f}s")
            
        except Exception as e:
            logger.warning(f"⚠️  Network cleanup encountered an error: {str(e)}")
            logger.debug("Stack trace:", exc_info=True)
            # Don't raise the exception to allow the reset to continue


def reset_rke2_node(connection_pool: ConnectionPool, node: Node, is_server: bool = True, reinstall: bool = False) -> bool:
    """Convenience function to reset a single RKE2 node.
    
    Args:
        connection_pool: Connection pool for SSH connections
        node: Node to reset
        is_server: Whether this is a server node
        reinstall: Whether to reinstall RKE2 after cleanup
        
    Returns:
        bool: True if reset was successful, False otherwise
    """
    import threading
    thread_name = threading.current_thread().name
    logger = logging.getLogger(__name__)
    
    logger.info(f"[{thread_name}] 🏁 Starting reset_rke2_node for {node.name} (is_server={is_server})")
    start_time = time.time()
    
    try:
        reset_handler = RKE2Reset(connection_pool)
        logger.info(f"[{thread_name}] 🔄 Created RKE2Reset handler for {node.name}")
        
        result = reset_handler.reset_node(node, is_server=is_server, reinstall=reinstall)
        
        duration = time.time() - start_time
        logger.info(f"[{thread_name}] ✅ Completed reset_rke2_node for {node.name} in {duration:.1f}s")
        return result
    except Exception as e:
        duration = time.time() - start_time
        logger.error(f"[{thread_name}] ❌ Error in reset_rke2_node for {node.name} after {duration:.1f}s: {e}", exc_info=True)
        raise
