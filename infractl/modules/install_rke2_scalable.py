# install_rke2_scalable.py
import os
import sys
import yaml
import time
import socket
import paramiko
import subprocess
import threading
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, Future
from itertools import islice

DEFAULT_INTERFACE = "bond0.100"
DEFAULT_SSH_USER = "kevin"
LOG_DIR = "logs"

@dataclass
class Node:
    name: str
    ip: str
    role: str  # "master" or "agent"
    ssh: Optional[paramiko.SSHClient] = field(default=None)

class RKE2Installer:
    def __init__(self, cluster_yaml_path: str, dry_run: bool = False):
        self.cluster_yaml_path = cluster_yaml_path
        self.config = self.load_yaml()
        self.nodes: List[Node] = self.parse_nodes()
        self.bootstrap_ip = next(n.ip for n in self.nodes if n.role == "master")
        self.token = "SuperSecureToken123"
        self.interface = DEFAULT_INTERFACE
        self.ssh_user = DEFAULT_SSH_USER
        self.ssh_key_path = os.path.expanduser(self.config.get("ssh_key", "~/.ssh/id_rsa"))
        self.dry_run = dry_run
        Path(LOG_DIR).mkdir(exist_ok=True)

    def load_yaml(self):
        with open(self.cluster_yaml_path, "r") as f:
            return yaml.safe_load(f)

    def parse_nodes(self):
        """Parse and create Node objects from the configuration in parallel.
        
        Returns:
            List[Node]: List of Node objects for all masters and agents
        """
        nodes = []
        
        def create_node(role: str, node_data: dict) -> Node:
            """Helper function to create a single Node object"""
            name = node_data.get('name', f"{role}-{node_data['ip']}")
            return Node(
                name=name,
                ip=node_data['ip'],
                role=role
            )
        
        # Process masters and agents in parallel
        with ThreadPoolExecutor(max_workers=10) as executor:
            # Submit all master nodes
            master_futures = [
                executor.submit(create_node, 'master', master)
                for master in self.config.get("masters", [])
            ]
            
            # Submit all agent nodes
            agent_futures = [
                executor.submit(create_node, 'agent', agent)
                for agent in self.config.get("agents", [])
            ]
            
            # Collect results as they complete
            for future in master_futures + agent_futures:
                try:
                    nodes.append(future.result())
                except Exception as e:
                    print(f"Error creating node: {e}")
        
        # Ensure we have at least one master node
        if not any(node.role == 'master' for node in nodes):
            raise ValueError("At least one master node must be defined")
            
        return nodes

    def batch(self, iterable, size):
        it = iter(iterable)
        while True:
            chunk = list(islice(it, size))
            if not chunk:
                break
            yield chunk

    def ssh_connect(self, node: Node):
        try:
            key = paramiko.RSAKey.from_private_key_file(self.ssh_key_path)
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(node.ip, username=self.ssh_user, pkey=key, timeout=10)
            node.ssh = client
            return True
        except Exception as e:
            self.log(node, f"[SSH FAIL] {e}")
            return False

    def _sftp_put(self, node: Node, local_path: str, remote_path: str):
        """Upload a file to the remote node using SFTP."""
        if not self.ssh_connect(node):
            raise Exception(f"Failed to connect to {node.name}")
            
        try:
            with node.ssh.open_sftp() as sftp:
                sftp.put(local_path, remote_path)
        except Exception as e:
            raise Exception(f"Failed to upload {local_path} to {node.name}:{remote_path}: {str(e)}")

    def ssh_exec(self, node: Node, command: str, check: bool = True, timeout: int = 120) -> str:
        """Execute a command on the remote node with improved error handling and retries.
        
        Args:
            node: The node to execute the command on
            command: The command to execute
            check: If True, raise an exception if the command fails
            timeout: Command timeout in seconds (default: 120)
            
        Returns:
            str: The command output
        """
        import socket
        max_retries = 3
        last_error = None
        
        for attempt in range(1, max_retries + 1):
            try:
                if not self.ssh_connect(node):
                    raise Exception(f"Failed to connect to {node.name} via SSH")
                
                start_time = time.time()
                self.log(node, f"$ {command} [attempt {attempt}/{max_retries}, timeout={timeout}s]")
                
                # Set up the command with a timeout
                stdin, stdout, stderr = node.ssh.exec_command(
                    f'set -euo pipefail; {command}',
                    get_pty=True,
                    timeout=timeout
                )
                
                # Set a timeout for the channel operations
                channel = stdout.channel
                
                # Wait for command to complete or timeout
                while not channel.exit_status_ready():
                    if time.time() - start_time > timeout:
                        raise socket.timeout(f"Command timed out after {timeout} seconds")
                    time.sleep(0.5)  # Increased sleep to reduce CPU usage
                
                # Get the exit status and output
                exit_status = channel.recv_exit_status()
                output = stdout.read().decode().strip()
                error = stderr.read().decode().strip()
                
                # Log the results
                if output:
                    self.log(node, output)
                if error:
                    self.log(node, f"[ERROR] {error}")
                
                elapsed = time.time() - start_time
                self.log(node, f"[Command completed in {elapsed:.1f}s with status {exit_status}]")
                
                # Raise an exception if the command failed and check=True
                if check and exit_status != 0:
                    error_msg = f"Command '{command}' failed with exit status {exit_status}"
                    if error:
                        error_msg += f": {error}"
                    raise Exception(error_msg)
                
                return output
                
            except (socket.timeout, socket.error, paramiko.SSHException) as e:
                last_error = e
                error_type = type(e).__name__
                self.log(node, f"⚠️  SSH {error_type} (attempt {attempt}/{max_retries}): {str(e)}")
                
                # Close connection on error to ensure clean state for retry
                try:
                    if hasattr(node, 'ssh') and node.ssh is not None:
                        node.ssh.close()
                        node.ssh = None
                except:
                    pass
                
                if attempt == max_retries:
                    break
                    
                # Exponential backoff before retry
                wait_time = 5 * attempt
                self.log(node, f"⏳ Retrying in {wait_time} seconds...")
                time.sleep(wait_time)
                
            except Exception as e:
                last_error = e
                self.log(node, f"❌ Unexpected error (attempt {attempt}/{max_retries}): {str(e)}")
                if attempt == max_retries:
                    break
                time.sleep(5)
        
        # If we get here, all retries failed
        error_msg = f"Command failed after {max_retries} attempts"
        if last_error:
            error_msg += f": {str(last_error)}"
        if check:
            raise Exception(error_msg)
        return ""

    def get_node_ip(self, node: Node):
        """Get the node's IP address from its configuration.
        
        This method returns the IP from the node's configuration as specified in the 
        cluster YAML file, with validation and debugging information.
        
        Args:
            node: The node object
            
        Returns:
            str: The node's IP address from configuration
            
        Raises:
            Exception: If the node's IP is not set, invalid, or unreachable
        """
        # First check if IP is configured in the node object
        if not hasattr(node, 'ip') or not node.ip:
            error_msg = "❌ Node IP is not configured in the cluster YAML"
            self.log(node, error_msg)
            raise Exception(error_msg)
        
        # Clean and validate the IP address
        node_ip = node.ip.split('\n')[0].strip()
        if not self._is_valid_ip(node_ip):
            error_msg = f"❌ Invalid IP address in node configuration: {node_ip}"
            self.log(node, error_msg)
            raise Exception(error_msg)
        
        # Log network interfaces for debugging
        try:
            self.log(node, f"🔍 Network interfaces on {node.name}:")
            interfaces = self.ssh_exec(node, "ip -4 -o addr show", check=False)
            self.log(node, interfaces)
            
            self.log(node, f"🔍 Routing table on {node.name}:")
            routes = self.ssh_exec(node, "ip route", check=False)
            self.log(node, routes)
            
            self.log(node, f"🔍 Hostname information for {node.name}:")
            hostname = self.ssh_exec(node, "hostname -f; hostname -i", check=False)
            self.log(node, hostname)
            
            # Verify the IP is configured on an interface
            ip_check = self.ssh_exec(
                node, 
                f"ip -4 -o addr show | grep -w {node_ip} || echo 'IP_NOT_FOUND'",
                check=False
            )
            
            if 'IP_NOT_FOUND' in ip_check:
                error_msg = f"❌ Configured IP {node_ip} not found on any network interface"
                self.log(node, error_msg)
                raise Exception(error_msg)
                
        except Exception as e:
            self.log(node, f"⚠️  Warning: Could not gather complete network info: {str(e)}")
        
        self.log(node, f"✅ Using configured node IP: {node_ip}")
        return node_ip
    
    def _is_valid_ip(self, ip: str) -> bool:
        """Check if the given string is a valid IPv4 address."""
        if not ip or not isinstance(ip, str):
            return False
        parts = ip.split('.')
        if len(parts) != 4:
            return False
        try:
            return all(0 <= int(part) < 256 for part in parts)
        except (ValueError, TypeError):
            return False

    def write_config_yaml(self, node: Node, ip: str):
        """Generate RKE2 configuration with deterministic IP assignment.
        
        Args:
            node: The node object containing node information
            ip: The IP address passed to the method (should be the node's IP)
            
        Returns:
            None
        """
        self.log(node, f"🔍 ====== STARTING CONFIG GENERATION ======")
        self.log(node, f"🔍 Node: {getattr(node, 'name', 'N/A')} (role: {getattr(node, 'role', 'N/A')})")
        
        # The IP should already be resolved and validated in handle_node
        node_ip = ip.strip() if ip else None
        if not node_ip:
            raise ValueError("No valid IP address provided for node configuration")
            
        self.log(node, f"🔍 ====== STARTING CONFIG GENERATION ======")
        self.log(node, f"🔍 Node: {node.name} (role: {node.role})")
        self.log(node, f"🔍 Using validated node IP: {node_ip}")
        
        # Ensure the node's IP is up to date
        node.ip = node_ip
        
        # Get all master node IPs for tls-san (including the current node if it's a master)
        master_ips = []
        if hasattr(self, 'nodes'):
            for n in self.nodes:
                if getattr(n, 'role', None) == 'master':
                    # For master nodes, try to use their configured IP
                    if hasattr(n, 'ip') and n.ip:
                        master_ip = n.ip.split('\n')[0].strip()
                        if master_ip and master_ip not in master_ips:
                            master_ips.append(master_ip)
                            self.log(node, f"  - Added master node IP: {master_ip}")
        
        # If no master IPs were found, use the current node's IP
        if not master_ips and node.role == 'master':
            master_ips.append(node_ip)
            self.log(node, f"  - Added current node as master IP: {node_ip}")
        
        # Log the final tls-san list
        if master_ips:
            self.log(node, f"✅ Final tls-san list: {', '.join(master_ips)}")
        else:
            self.log(node, "⚠️  No master IPs found for tls-san - this may cause issues with cluster communication")
        
        # Create the base config with node-specific settings
        config = {}
        
        # Common configuration for all nodes
        common_config = {
            'cni': 'cilium',
            'token': self.token,
            'node-ip': node.ip,
            'node-name': node.name,
            'node-external-ip': node.ip,
            'with-node-id': True,
            'disable': [
                'rke2-cilium',  # Using our own Cilium installation
                'rke2-canal',
                'rke2-coredns',
                'rke2-ingress-nginx',
                'rke2-metrics-server'
            ]
        }
        
        # Role-specific configuration
        if node.role == 'master':
            config.update({
                'advertise-address': node.ip,
                'bind-address': node.ip,
                'tls-san': master_ips,
                'kube-apiserver-arg': [
                    'default-not-ready-toleration-seconds=30',
                    'default-unreachable-toleration-seconds=30',
                    'feature-gates=RotateKubeletServerCertificate=true'
                ],
                'kube-controller-manager-arg': [
                    'node-monitor-grace-period=20s',
                    'node-monitor-period=5s',
                    'feature-gates=RotateKubeletServerCertificate=true'
                ]
            })
        else:
            # Agent configuration
            if master_ips:  # Use the first master as the server URL
                config['server'] = f'https://{master_ips[0]}:9345'
            
        # Common kubelet and kube-proxy arguments for all nodes
        kubelet_args = [
            f'node-ip={node.ip}',
            f'node-labels=node.kubernetes.io/instance-type=rke2',
            'cloud-provider=external',
            'cgroup-driver=systemd',
            'volume-plugin-dir=/var/lib/kubelet/volumeplugins',
            'read-only-port=0',
            'feature-gates=RotateKubeletServerCertificate=true',
            'serialize-image-pulls=false',
            'fail-swap-on=false'
        ]
        
        # Add node taints for etcd nodes
        if node.role == 'etcd' or (node.role == 'master' and getattr(node, 'etcd', True)):
            kubelet_args.append('register-with-taints=node-role.kubernetes.io/etcd:NoSchedule')
        
        config['kubelet-arg'] = kubelet_args
        
        # Kube-proxy configuration
        config['kube-proxy-arg'] = [
            'metrics-bind-address=0.0.0.0:10249',
            # Removed metrics-bind-address-ipvs-sctp as it's not supported in this kube-proxy version
        ]
        
        # Merge common config with role-specific config
        config = {**common_config, **config}
        
        # Log the final configuration (without sensitive data)
        log_config = config.copy()
        if 'token' in log_config:
            log_config['token'] = '***REDACTED***'
        self.log(node, f"🔧 Final configuration: {log_config}")
        
        # For agent nodes, ensure we have a server URL and token
        if node.role == 'agent':
            # If no server URL was set from master_ips, try to get it from the first master node
            if 'server' not in config:
                master_nodes = [n for n in getattr(self, 'nodes', []) if getattr(n, 'role') == 'master']
                if master_nodes:
                    master_ip = master_nodes[0].ip.split('\n')[0].strip()
                    if master_ip:
                        server_url = f'https://{master_ip}:9345'
                        config['server'] = server_url
                        self.log(node, f"🔗 Configuring agent to connect to master at {master_ip}")
                    else:
                        self.log(node, "⚠️  Could not determine master IP for agent configuration")
                else:
                    self.log(node, "⚠️  No master nodes found for agent configuration")
            else:
                server_url = config['server']
            
            # Ensure we have a token
            if 'token' not in config and hasattr(self, 'token') and self.token:
                config['token'] = self.token
                self.log(node, "✅ Configured agent with cluster token")
            elif 'token' not in config:
                self.log(node, "⚠️  No token available for agent configuration")
            
            # Add node-specific configurations
            config.update({
                'with-node-id': True,
                'kubelet-arg': [
                    f'node-ip={node.ip}',
                    'node-labels=node.kubernetes.io/instance-type=rke2',
                    'cloud-provider=external',
                    'cgroup-driver=systemd',
                    'volume-plugin-dir=/var/lib/kubelet/volumeplugins',
                    'read-only-port=0',
                    'feature-gates=RotateKubeletServerCertificate=true',
                    'serialize-image-pulls=false',
                    'fail-swap-on=false'
                ]
            })
            
            # Log the agent configuration (without sensitive data)
            safe_config = config.copy()
            if 'token' in safe_config:
                safe_config['token'] = '***REDACTED***'
            self.log(node, f"🔧 Agent configuration: {safe_config}")
            
            # Create environment file for the service
            env_file = "/etc/rancher/rke2/agent.env"
            env_content = f'''RKE2_URL={server_url if 'server_url' in locals() else ''}
RKE2_TOKEN={self.token if hasattr(self, 'token') else ''}
RKE2_NODE_IP={node_ip}
RKE2_NODE_NAME={node.name}
RKE2_KUBECONFIG_MODE=0644
RKE2_KUBECONFIG_OUTPUT=/etc/rancher/rke2/config.yaml
'''
            
            # Write environment file
            self.ssh_exec(node, 'sudo mkdir -p /etc/rancher/rke2')
            self.ssh_exec(node, f'sudo bash -c \'cat > {env_file} << EOL\n{env_content}\nEOL\'')
            self.ssh_exec(node, f'sudo chmod 600 {env_file}')
            
            # Create systemd service override to ensure token is passed
            override_dir = "/etc/systemd/system/rke2-agent.service.d"
            override_file = f"{override_dir}/10-env.conf"
            override_content = f'''[Service]
EnvironmentFile={env_file}
'''
            
            self.ssh_exec(node, f'sudo mkdir -p {override_dir}')
            self.ssh_exec(node, f'sudo bash -c \'cat > {override_file} << EOL\n{override_content}\nEOL\'')
            self.ssh_exec(node, 'sudo systemctl daemon-reload')
        
        try:
            self.log(node, "🔧 Preparing RKE2 configuration...")
            
            # Convert to YAML and write to file
            try:
                config_yaml = yaml.dump(config, default_flow_style=False, sort_keys=False)
                self.log(node, f"✅ Generated RKE2 config YAML")
            except Exception as e:
                self.log(node, f"❌ Failed to generate YAML: {str(e)}")
                return False
            
            # Create a temporary file with the config
            temp_path = '/tmp/rke2-config.yaml'
            try:
                with open(temp_path, 'w') as f:
                    f.write(config_yaml)
                self.log(node, f"✅ Wrote config to temporary file: {temp_path}")
            except Exception as e:
                self.log(node, f"❌ Failed to write temporary config file: {str(e)}")
                return False
            
            # Upload the config file to the node
            try:
                self._sftp_put(node, temp_path, temp_path)
                self.log(node, f"✅ Uploaded config to node: {temp_path}")
            except Exception as e:
                self.log(node, f"❌ Failed to upload config to node: {str(e)}")
                return False
            
            # Create the directory structure if it doesn't exist
            config_dir = '/etc/rancher/rke2'
            try:
                self.ssh_exec(node, f'sudo mkdir -p {config_dir}', check=True)
                self.log(node, f"✅ Created directory: {config_dir}")
            except Exception as e:
                self.log(node, f"❌ Failed to create directory {config_dir}: {str(e)}")
                return False
            
            # Move to the correct location with proper permissions
            dest_path = f"{config_dir}/config.yaml"
            try:
                # First check if the destination exists and back it up
                self.ssh_exec(node, f'sudo test -f {dest_path} && sudo cp {dest_path} {dest_path}.bak || true', check=False)
                
                # Move the new config in place
                self.ssh_exec(node, f'sudo mv {temp_path} {dest_path} && sudo chmod 600 {dest_path}', check=True)
                self.log(node, f"✅ Moved config to {dest_path} and set permissions")
                
                # Verify the file was written
                result = self.ssh_exec(node, f'sudo test -f {dest_path} && echo exists || echo missing', check=False).strip()
                if 'exists' in result:
                    self.log(node, f"✅ Successfully verified config at {dest_path}")
                    
                    # Log the first few lines of the config for verification
                    config_preview = self.ssh_exec(node, f'sudo head -n 10 {dest_path} 2>/dev/null || echo "Could not read config"', check=False)
                    self.log(node, f"📋 Config preview (first 10 lines):\n{config_preview}")
                    
                    return True
                else:
                    self.log(node, f"❌ Failed to verify config file at {dest_path}")
                    return False
                    
            except Exception as e:
                self.log(node, f"❌ Failed to move config to {dest_path}: {str(e)}")
                return False
        
        except Exception as e:
            self.log(node, f"❌ Failed to write config: {str(e)}")
            # Log the full traceback for debugging
            import traceback
            self.log(node, f"🔍 Traceback: {traceback.format_exc()}")
            return False

# ... (rest of the code remains the same)
    def is_rke2_installed(self, node: Node):
        return "active" in self.ssh_exec(node, "sudo systemctl is-active rke2-server || sudo systemctl is-active rke2-agent")

    def is_rke2_service_active(self, node: Node) -> bool:
        """Check if RKE2 service is active on the node."""
        try:
            rke2_type = "server" if node.role == "master" else "agent"
            status = self.ssh_exec(node, f"sudo systemctl is-active rke2-{rke2_type}", check=False).strip()
            return status == 'active'
        except Exception as e:
            self.logger.warning(f"Failed to check RKE2 service status on {node.name}: {e}")
            return False

    def _check_service_status(self, node: Node, service_name: str) -> tuple[bool, str]:
        """Check service status and return (is_running, status_output)."""
        try:
            # Check if service is active
            try:
                status = self.ssh_exec(node, f'sudo systemctl is-active {service_name}', check=True).strip()
                if status == 'active':
                    return True, status
                
                # If not active, get more details
                journal = self.ssh_exec(
                    node, 
                    f'sudo journalctl -u {service_name} -n 20 --no-pager', 
                    check=False
                )
                return False, f"Status: {status}\nLast logs:\n{journal}"
                
            except Exception as e:
                # If the service doesn't exist or other error, check if it's installed
                if "not-found" in str(e).lower() or "no such file" in str(e).lower():
                    return False, f"Service {service_name} is not installed"
                return False, f"Error checking service status: {str(e)}"
                
        except Exception as e:
            return False, f"Unexpected error: {str(e)}"

    def verify_cluster_health(self, node: Node) -> bool:
        """Verify the health of the RKE2 cluster.
        
        Args:
            node: A master node to run health checks from
            
        Returns:
            bool: True if cluster is healthy, False otherwise
        """
        try:
            self.log(node, "🔍 Verifying cluster health...")
            
            # Check node status
            self.log(node, "📊 Node status:")
            self.ssh_exec(node, 
                'sudo /var/lib/rancher/rke2/bin/kubectl --kubeconfig=/etc/rancher/rke2/rke2.yaml get nodes -o wide', 
                check=True
            )
            
            # Check pod status
            self.log(node, "📦 Pod status:")
            self.ssh_exec(node, 
                'sudo /var/lib/rancher/rke2/bin/kubectl --kubeconfig=/etc/rancher/rke2/rke2.yaml get pods -A --field-selector=status.phase!=Running', 
                check=False
            )
            
            # Check component status
            self.log(node, "⚙️  Component status:")
            self.ssh_exec(node, 
                'sudo /var/lib/rancher/rke2/bin/kubectl --kubeconfig=/etc/rancher/rke2/rke2.yaml get cs', 
                check=True
            )
            
            # Check for any error events
            self.log(node, "⚠️  Recent error events:")
            self.ssh_exec(node, 
                'sudo /var/lib/rancher/rke2/bin/kubectl --kubeconfig=/etc/rancher/rke2/rke2.yaml get events --field-selector=type==Warning -A --sort-by=.metadata.creationTimestamp', 
                check=False
            )
            
            self.log(node, "✅ Cluster health check passed")
            return True
            
        except Exception as e:
            self.log(node, f"❌ Cluster health check failed: {str(e)}")
            return False

    def install_system_dependencies(self, node: Node) -> bool:
        """Install required system dependencies for RKE2.
        
        Args:
            node: The node to install dependencies on
            
        Returns:
            bool: True if dependencies were installed successfully
        """
        try:
            self.log(node, "🔧 Installing system dependencies...")
            
            # Detect package manager
            try:
                self.ssh_exec(node, "command -v apt-get", check=False)
                pkg_manager = "apt-get"
                update_cmd = "sudo apt-get update -y"
                install_cmd = "sudo DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends"
            except:
                pkg_manager = "yum"
                update_cmd = "sudo yum makecache -y"
                install_cmd = "sudo yum install -y"
            
            # Update package lists
            self.ssh_exec(node, update_cmd, check=True, timeout=300)
            
            # Base packages (excluding time sync daemons)
            base_packages = [
                "curl", "jq", "ipvsadm", "ipset", "socat", 
                "conntrack", "ebtables", "ethtool"
            ]
            
            # Install base packages first
            self.ssh_exec(
                node, 
                f"{install_cmd} {' '.join(base_packages)}", 
                check=True, 
                timeout=600
            )
            
            # Handle time synchronization - prefer chrony
            try:
        
                # Stop and disable systemd-timesyncd if it exists
                self.ssh_exec(
                    node, 
                    "if systemctl list-unit-files | grep -q systemd-timesyncd; then "
                    "sudo systemctl stop systemd-timesyncd && "
                    "sudo systemctl disable systemd-timesyncd; fi",
                    check=False
                )
                
                # Verify chrony is working
                self.ssh_exec(
                    node,
                    "sudo chronyc tracking",
                    check=True
                )
                
            except Exception as e:
                self.log(node, f"⚠️  Warning: Failed to configure time synchronization: {str(e)}")
                self.log(node, "⚠️  Time synchronization might not work correctly")
            
            # Disable swap
            try:
                self.ssh_exec(node, "sudo swapoff -a", check=False)
                self.ssh_exec(node, "sudo sed -i '/swap/s/^/#/' /etc/fstab", check=False)
            except Exception as e:
                self.log(node, f"⚠️  Warning: Failed to disable swap: {str(e)}")
            
            # Enable IP forwarding and bridge settings
            try:
                self.ssh_exec(
                    node,
                    'echo -e "net.ipv4.ip_forward = 1\nnet.bridge.bridge-nf-call-iptables = 1" | ' \
                    'sudo tee /etc/sysctl.d/99-kubernetes-cri.conf',
                    check=True
                )
                self.ssh_exec(node, "sudo sysctl --system", check=True)
            except Exception as e:
                self.log(node, f"⚠️  Warning: Failed to configure network settings: {str(e)}")
            
            # Install additional container runtime dependencies
            try:
                runtime_pkgs = [
                    "apt-transport-https",
                    "ca-certificates",
                    "gnupg",
                    "lsb-release"
                ]
                self.ssh_exec(
                    node,
                    f"{install_cmd} {' '.join(runtime_pkgs)}",
                    check=True,
                    timeout=300
                )
            except Exception as e:
                self.log(node, f"⚠️  Warning: Failed to install additional packages: {str(e)}")
            
            self.log(node, "✅ System dependencies installed successfully")
            return True
            
        except Exception as e:
            self.log(node, f"❌ Failed to install system dependencies: {str(e)}")
            return False

    def is_rke2_healthy(self, node: Node, service_name: str) -> bool:
        """Check if RKE2 service is healthy.
        
        Args:
            node: The node to check
            service_name: Name of the service to check
            
        Returns:
            bool: True if service is healthy, False otherwise
        """
        try:
            # Check if service is running
            is_running, status = self._check_service_status(node, service_name)
            if not is_running:
                self.log(node, f"⚠️  Service {service_name} is not running")
                return False
            
            # For server nodes, check if kubelet is healthy
            if 'server' in service_name:
                kubelet_status = self.ssh_exec(
                    node,
                    'curl -sSk "https://localhost:10250/healthz" 2>/dev/null || echo "unhealthy"',
                    check=False
                ).strip()
                
                if kubelet_status != 'ok':
                    self.log(node, f"⚠️  Kubelet health check failed: {kubelet_status}")
                    return False
            
            # Check if the service is properly enabled
            is_enabled = self.ssh_exec(
                node,
                f'systemctl is-enabled {service_name} 2>/dev/null || echo "disabled"',
                check=False
            ).strip() == 'enabled'
            
            if not is_enabled:
                self.log(node, f"⚠️  Service {service_name} is not enabled to start on boot")
                
            return True
            
        except Exception as e:
            self.log(node, f"⚠️  Health check failed: {str(e)}")
            return False

    def _install_rke2_attempt(self, node: Node, rke2_type: str, service_name: str) -> bool:
        """Internal method to attempt RKE2 installation once.
        
        Args:
            node: The node to install RKE2 on
            rke2_type: Type of RKE2 installation ('server' or 'agent')
            service_name: Name of the RKE2 service
            
        Returns:
            bool: True if installation was successful, False otherwise
        """
        try:
            if not self.ssh_connect(node):
                self.log(node, "❌ Failed to establish SSH connection")
                return False
            
            # Check if RKE2 is already installed and healthy
            if self.is_rke2_healthy(node, service_name):
                self.log(node, f"✅ RKE2 {rke2_type} is already installed and healthy")
                return True
            
            self.log(node, f"🔧 Starting RKE2 {rke2_type} installation...")
            
            # Install system dependencies first
            if not self.install_system_dependencies(node):
                self.log(node, "⚠️  Failed to install system dependencies")
                return False
            
            # Get node IP
            try:
                node_ip = self.get_node_ip(node)
                self.log(node, f"📡 Detected node IP: {node_ip}")
            except Exception as e:
                self.log(node, f"⚠️  Failed to detect node IP: {str(e)}")
                node_ip = node.ip  # Fall back to the IP from config
            
            # Configure RKE2 if not already configured
            if not self.is_config_valid(node, node_ip):
                self.log(node, "📝 Writing RKE2 configuration...")
                self.write_config_yaml(node, node_ip)
            else:
                self.log(node, "✅ RKE2 configuration is already valid")
            
            # Install RKE2 if not already installed
            if not self.is_rke2_installed(node):
                self.log(node, f"📥 Downloading and installing RKE2 {rke2_type}...")
                
            self.log(node, f"🚀 Starting RKE2 {rke2_type} service...")
            try:
                self.ssh_exec(node, f"sudo systemctl restart {service_name}", check=True, timeout=120)
                self.log(node, f"✅ {service_name} started successfully")
                return True
            except Exception as e:
                self.log(node, f"❌ Failed to start {service_name}: {str(e)}")
                # Get service status and logs
            start_time = time.time()
            
            while time.time() - start_time < max_wait:
                if self.is_rke2_healthy(node, service_name):
                    break
                    
                self.log(node, f"⏳ Waiting for RKE2 {rke2_type} to become healthy...")
                time.sleep(5)
            else:
                self.log(node, f"❌ Timed out waiting for RKE2 {rke2_type} to become healthy")
                # Collect logs for debugging
                try:
                    journal = self.ssh_exec(
                        node, 
                        f'sudo journalctl -u {service_name} -n 50 --no-pager', 
                        check=False
                    )
                    self.log(node, f"📋 Service logs:\n{journal}")
                except Exception as log_err:
                    self.log(node, f"⚠️  Could not retrieve service logs: {str(log_err)}")
                return False
            
            # Additional checks for master nodes
            if rke2_type == 'server':
                self.log(node, "🔍 Running additional checks for master node...")
                
                # Verify kubeconfig exists and is accessible
                kubeconfig_path = "/etc/rancher/rke2/rke2.yaml"
                kubeconfig_exists = self.ssh_exec(
                    node, 
                    f"sudo test -f {kubeconfig_path} && echo exists || echo missing",
                    check=False
                ).strip() == 'exists'
                
                if not kubeconfig_exists:
                    self.log(node, f"❌ Kubeconfig not found at {kubeconfig_path}")
                    return False
                
                # Verify API server health
                api_health = self.ssh_exec(
                    node,
                    'curl -sk https://localhost:6443/healthz 2>/dev/null || echo "unhealthy"',
                    check=False
                ).strip()
                
                if api_health != 'ok':
                    self.log(node, f"❌ API server is not healthy: {api_health}")
                    return False
                
                # Verify cluster health
                if not self.verify_cluster_health(node):
                    self.log(node, "⚠️  Cluster health check failed after installation")
                    return False
            
            self.log(node, f"✅ RKE2 {rke2_type} installation completed successfully")
            return True
            
        except Exception as e:
            error_msg = str(e)
            self.log(node, f"❌ Installation failed: {error_msg}")
            
            # Collect logs for debugging
            try:
                journal = self.ssh_exec(
                    node, 
                    f'sudo journalctl -u {service_name} -n 50 --no-pager', 
                    check=False
                )
                self.log(node, f"📋 Service logs:\n{journal}")
                
                # Check for common issues
                if "connection refused" in error_msg.lower():
                    self.log(node, "🔧 Detected connection refused - checking service status...")
                    status = self.ssh_exec(node, f'sudo systemctl status {service_name} || true', check=False)
                    self.log(node, f"🔧 Service status: {status}")
                
            except Exception as log_err:
                self.log(node, f"⚠️  Could not retrieve service logs: {str(log_err)}")
            
            return False
    
    def install_rke2(self, node: Node, max_retries: int = 3, retry_delay: int = 30) -> bool:
        """Install RKE2 on a node with retries and validation.
        
        This method is idempotent and can be safely run multiple times.
        
        Args:
            node: The node to install RKE2 on
            max_retries: Maximum number of retry attempts
            retry_delay: Delay between retries in seconds
            
        Returns:
            bool: True if installation was successful or already installed, False otherwise
        """
        rke2_type = 'server' if node.role == 'master' else 'agent'
        service_name = f'rke2-{rke2_type}'
        
        # Log initial state
        self.log(node, f"🔍 Starting RKE2 installation for {node.name} (role: {node.role})")
        self.log(node, f"🔧 RKE2 type: {rke2_type}, Service: {service_name}")
        self.log(node, f"🔄 Max retries: {max_retries}, Retry delay: {retry_delay}s")
        
        for attempt in range(1, max_retries + 1):
            attempt_start = time.time()
            self.log(node, f"\n🔄 Attempt {attempt}/{max_retries} starting...")
            
            # Log pre-attempt state
            self.log(node, "📋 Pre-attempt state:")
            self._log_system_state(node, service_name)
            
            if attempt > 1:
                retry_wait = max(0, retry_delay - (time.time() - attempt_start))
                if retry_wait > 0:
                    self.log(node, f"⏳ Waiting {retry_wait:.1f}s before retry...")
                    time.sleep(retry_wait)
            
            # Run the installation attempt
            attempt_success = self._install_rke2_attempt(node, rke2_type, service_name)
            
            # Log post-attempt state
            self.log(node, f"📋 Post-attempt state (success: {attempt_success}):")
            self._log_system_state(node, service_name)
            
            if attempt_success:
                self.log(node, f"✅ Installation successful on attempt {attempt}")
                return True
                
            attempt_duration = time.time() - attempt_start
            self.log(node, f"❌ Attempt {attempt} failed after {attempt_duration:.1f}s")
            
            # Clean up before retry if not the last attempt
            if attempt < max_retries:
                self.log(node, "🧹 Performing minimal cleanup before retry...")
                try:
                    # Log service status before cleanup
                    self.log(node, "📋 Service status before cleanup:")
                    self._log_service_status(node, service_name)
                    
                    # Just stop the service without disabling it
                    self.log(node, f"🛑 Stopping {service_name}...")
                    stop_cmd = f'sudo systemctl stop {service_name} || true'
                    stop_output = self.ssh_exec(node, stop_cmd, check=False)
                    self.log(node, f"  Stop command output: {stop_output.strip() if stop_output else 'No output'}")
                    
                    # Only remove the server token file if it exists, which can prevent join issues
                    self.log(node, "🧹 Cleaning up kubelet args...")
                    cleanup_cmd = 'sudo rm -f /etc/rancher/rke2/config.yaml.d/*-kubelet-args || true'
                    cleanup_output = self.ssh_exec(node, cleanup_cmd, check=False)
                    
                    # Clear any error states in systemd
                    self.log(node, "🔄 Resetting systemd failed state...")
                    reset_cmd = f'sudo systemctl reset-failed {service_name} || true'
                    reset_output = self.ssh_exec(node, reset_cmd, check=False)
                    
                    # Log service status after cleanup
                    self.log(node, "📋 Service status after cleanup:")
                    self._log_service_status(node, service_name)
                    
                except Exception as cleanup_err:
                    self.log(node, f"⚠️  Minimal cleanup failed: {str(cleanup_err)}")
                    import traceback
                    self.log(node, f"⚠️  Cleanup traceback: {traceback.format_exc()}")
                    self.log(node, "⚠️  Continuing with retry despite cleanup error")
        
        # Final state dump before giving up
        self.log(node, "❌❌❌ FAILED TO INSTALL RKE2 - FINAL STATE ❌❌❌")
        self._log_system_state(node, service_name, verbose=True)
        
        # Collect critical logs for debugging
        try:
            self.log(node, "📜 Collecting critical logs...")
            logs = self.ssh_exec(
                node,
                'for log in $(sudo ls -1t /var/log/syslog* 2>/dev/null | head -3); do '
                'echo "===== $log ====="; sudo tail -n 50 "$log" || true; done',
                check=False
            )
            self.log(node, f"📋 System logs:\n{logs}")
            
            # Check for disk space
            disk = self.ssh_exec(node, 'df -h', check=False)
            self.log(node, f"💾 Disk usage:\n{disk}")
            
            # Check memory
            memory = self.ssh_exec(node, 'free -h', check=False)
            self.log(node, f"🧠 Memory usage:\n{memory}")
            
        except Exception as log_err:
            self.log(node, f"⚠️  Failed to collect debug logs: {str(log_err)}")
        
        self.log(node, f"❌ Failed to install RKE2 after {max_retries} attempts")
        return False
        
    def _log_service_status(self, node: Node, service_name: str) -> None:
        """Log detailed service status information."""
        try:
            # Basic service status
            status_cmd = f'systemctl is-active {service_name} || echo "inactive"'
            status = self.ssh_exec(node, f'sudo {status_cmd}', check=False).strip()
            self.log(node, f"  Service {service_name} status: {status}")
            
            # Service unit status
            status_cmd = f'systemctl status {service_name} --no-pager || true'
            status_output = self.ssh_exec(node, f'sudo {status_cmd}', check=False)
            self.log(node, f"  Service status output:\n{status_output}")
            
            # Check for failed services
            failed_units = self.ssh_exec(node, 'systemctl list-units --failed --no-legend || true', check=False)
            if failed_units.strip():
                self.log(node, f"  Failed systemd units:\n{failed_units}")
                
        except Exception as e:
            self.log(node, f"⚠️  Failed to get service status: {str(e)}")
    
    def _log_system_state(self, node: Node, service_name: str, verbose: bool = False) -> None:
        """Log system state information for debugging."""
        try:
            # System information
            self.log(node, "  System information:")
            uptime = self.ssh_exec(node, 'uptime || true', check=False)
            self.log(node, f"  - Uptime: {uptime.strip() if uptime else 'N/A'}")
            
            # Service status
            self.log(node, "  Service status:")
            self._log_service_status(node, service_name)
            
            if verbose:
                # Network interfaces
                self.log(node, "  Network interfaces:")
                ifconfig = self.ssh_exec(node, 'ip addr show || ifconfig -a || true', check=False)
                self.log(node, f"{ifconfig}")
                
                # Listening ports
                self.log(node, "  Listening ports:")
                ports = self.ssh_exec(node, 'sudo netstat -tulnpe || sudo ss -tulnpe || true', check=False)
                self.log(node, f"{ports}")
                
                # Process list
                self.log(node, "  Running processes (RKE2/containerd related):")
                procs = self.ssh_exec(
                    node, 
                    'ps aux | grep -E "rke2|containerd|kube" | grep -v grep || true', 
                    check=False
                )
                self.log(node, f"{procs}")
                
        except Exception as e:
            self.log(node, f"⚠️  Failed to log system state: {str(e)}")
    
    def install_cilium_cni(self, node: Node) -> bool:
        """Install and configure Cilium CNI plugin using Helm.
        
        Args:
            node: The node to install Cilium on (should be a master node)
            
        Returns:
            bool: True if installation was successful, False otherwise
        """
        def log(msg):
            self.log(node, msg)
            
        try:
            log("🔧 Starting Cilium CNI installation using Helm...")
            
            # Install Helm if not already installed
            log("🔧 Installing Helm...")
            self.ssh_exec(
                node,
                "curl -fsSL -o get_helm.sh https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 && "
                "chmod 700 get_helm.sh && "
                "sudo ./get_helm.sh && "
                "rm get_helm.sh",
                check=True
            )
            
            # Add Cilium Helm repository
            log("📦 Adding Cilium Helm repository...")
            self.ssh_exec(
                node,
                "helm repo add cilium https://helm.cilium.io/ && "
                "helm repo update",
                check=True
            )
            
            # Install Cilium with recommended settings for RKE2
            log("🚀 Installing Cilium using Helm...")
            cmd = (
                'helm install cilium cilium/cilium ' +
                '--version 1.15.0 ' +
                '--namespace kube-system ' +
                '--set ipam.mode=kubernetes ' +
                '--set kubeProxyReplacement=strict ' +
                '--set k8sServiceHost=10.10.240.253 ' +
                '--set k8sServicePort=6443 ' +
                '--set hubble.enabled=true ' +
                '--set hubble.metrics.enabled=\"{dns,drop,tcp,flow,port-distribution,icmp,http}\" ' +
                '--set hubble.relay.enabled=true ' +
                '--set hubble.ui.enabled=true ' +
                '--set operator.replicas=1'
            )
            self.ssh_exec(node, cmd, check=True)
            
            # Wait for Cilium pods to be ready
            log("⏳ Waiting for Cilium pods to become ready...")
            timeout = time.time() + 600  # 10 minutes from now
            pods_ready = False
            
            while time.time() < timeout and not pods_ready:
                try:
                    # Check if Cilium pods are running and ready
                    result = self.ssh_exec(
                        node,
                        'sudo /var/lib/rancher/rke2/bin/kubectl --kubeconfig=/etc/rancher/rke2/rke2.yaml '\
                        'get pods -n kube-system -l k8s-app=cilium -o jsonpath=\'{range .items[*]}{.status.phase} {.status.containerStatuses[0].ready}\\n                        {end}\' 2>&1',
                        check=False
                    )
                    
                    # Parse the result
                    lines = [line.strip() for line in result.split('\n') if line.strip()]
                    if not lines:
                        log("No Cilium pods found")
                        time.sleep(5)
                        continue
                    
                    # Check all pods are running and ready
                    all_ready = True
                    for line in lines:
                        parts = line.split()
                        if len(parts) >= 2:
                            phase = parts[0]
                            ready = parts[1].lower() == 'true'
                            if phase != 'Running' or not ready:
                                all_ready = False
                                break
                    
                    if all_ready:
                        log("✅ All Cilium pods are running and ready")
                        pods_ready = True
                    else:
                        log(f"⏳ Waiting for Cilium pods to be ready... Current status: {result}")
                        time.sleep(5)
                except Exception as e:
                    log(f"⚠️  Error checking Cilium pods: {str(e)}")
                    time.sleep(5)
            
            if not pods_ready:
                log("⚠️  Timeout waiting for Cilium pods to become ready")
                return False
            
            # Verify Cilium status
            log("🔍 Verifying Cilium status...")
            try:
                status_cmd = (
                    'sudo /var/lib/rancher/rke2/bin/kubectl --kubeconfig=/etc/rancher/rke2/rke2.yaml '
                    'exec -n kube-system -t $(sudo /var/lib/rancher/rke2/bin/kubectl --kubeconfig=/etc/rancher/rke2/rke2.yaml '
                    'get pods -n kube-system -l k8s-app=cilium -o jsonpath=\'{.items[0].metadata.name}\') -- cilium status 2>&1'
                )
                status = self.ssh_exec(node, status_cmd, check=True)
                log(f"📊 Cilium status:\n{status}")
                
                # Basic check if Cilium is healthy
                if "Error" in status or "error" in status:
                    log("⚠️  Cilium status indicates potential issues")
                    return False
                
                log("✅ Cilium CNI installation and verification completed successfully")
                return True
                
            except Exception as e:
                log(f"⚠️  Could not verify Cilium status: {str(e)}")
                return False
            
        except Exception as e:
            log(f"❌ Failed to install Cilium CNI: {str(e)}")
            import traceback
            log(f"🔍 Error details: {traceback.format_exc()}")
            return False
        
        # Log to both file and console for better visibility
        def log(msg):
            self.log(node, msg)
            print(f"  {node.name}: {msg}")
            
        log(f"🔍 Starting RKE2 reset process on {node.name} ({node.role})")
        
        if not self.ssh_connect(node):
            log("❌ Failed to connect to node")
            return False
        
        try:
            # Step 1: Run rke2-killall.sh if it exists
            log("1️⃣ Looking for rke2-killall.sh...")
            killall_script = "/usr/local/bin/rke2-killall.sh"
            script_exists = self.ssh_exec(node, f"[ -f {killall_script} ] && echo exists || echo not_exists").strip()
            
            if script_exists == 'exists':
                log(f"  🔫 Found {killall_script}, executing...")
                result = self.ssh_exec(node, f"sudo {killall_script}", check=False, timeout=120)
                log(f"  🔫 {killall_script} completed with output: {result[:200]}..." if result else "  🔫 No output from killall script")
            else:
                log(f"  ℹ️  {killall_script} not found, skipping")
            
            # Step 2: Run rke2-uninstall.sh if it exists
            log("2️⃣ Looking for rke2-uninstall.sh...")
            uninstall_script = "/usr/local/bin/rke2-uninstall.sh"
            script_exists = self.ssh_exec(node, f"[ -f {uninstall_script} ] && echo exists || echo not_exists").strip()
            
            if script_exists == 'exists':
                log(f"  🧹 Found {uninstall_script}, executing...")
                result = self.ssh_exec(node, f"sudo {uninstall_script}", check=False, timeout=300)
                log(f"  🧹 {uninstall_script} completed with output: {result[:200]}..." if result else "  🧹 No output from uninstall script")
            else:
                log(f"  ℹ️  {uninstall_script} not found, skipping")
            
            # Step 3: Manual cleanup of any remaining files and configurations
            log("3️⃣ Starting manual cleanup of remaining files and configurations...")
            
            # Stop and disable services if they still exist
            log("  🛑 Stopping and disabling RKE2 services...")
            for service in ["rke2-server", "rke2-agent"]:
                log(f"  ⏳ Stopping {service}...")
                self.ssh_exec(node, f"sudo systemctl stop {service} 2>/dev/null || true", check=False, timeout=30)
                log(f"  ⏳ Disabling {service}...")
                self.ssh_exec(node, f"sudo systemctl disable {service} 2>/dev/null || true", check=False, timeout=30)
            
            # Kill any remaining processes
            log("  🔫 Killing any remaining RKE2 processes...")
            self.ssh_exec(node, "sudo pkill -9 rke2 2>/dev/null || true", check=False, timeout=30)
            self.ssh_exec(node, "sudo pkill -9 containerd-shim 2>/dev/null || true", check=False, timeout=30)
            
            # Remove RKE2 files and directories
            log("  🗑️  Removing RKE2 files and directories...")
            dirs_to_remove = [
                "/etc/rancher/rke2",
                "/var/lib/rancher/rke2",
                "/var/lib/kubelet",
                "/var/lib/rancher/etcd",
                "/var/lib/rancher/kubelet",
                "/var/lib/rancher/etcd-snapshots",
                "/var/lib/rancher/etcd-backups",
                "/var/lib/rancher/management-state",
                "/var/lib/rancher/rke2/server/db/etcd",
                "/var/lib/rancher/rke2/agent/containerd"
            ]
            
            for directory in dirs_to_remove:
                log(f"  🗑️  Removing directory: {directory}")
                self.ssh_exec(node, f"sudo rm -rf {directory} 2>/dev/null || true", check=False, timeout=120)
            
            # Clean up CNI and network configurations
            log("  🌐 Cleaning up CNI and network configurations...")
            self.ssh_exec(node, "sudo rm -rf /etc/cni/net.d/* /etc/cni/bin/* /opt/cni/bin/* 2>/dev/null || true", check=False, timeout=60)
            
            # Reset iptables
            log("  🔄 Resetting iptables rules...")
            iptables_cmds = [
                "sudo iptables -F",
                "sudo iptables -t nat -F",
                "sudo iptables -t mangle -F",
                "sudo iptables -X",
                "sudo iptables -t nat -X",
                "sudo iptables -t mangle -X",
                "sudo iptables -P INPUT ACCEPT",
                "sudo iptables -P FORWARD ACCEPT",
                "sudo iptables -P OUTPUT ACCEPT"
            ]
            for cmd in iptables_cmds:
                log(f"  🔄 Running: {cmd}")
                self.ssh_exec(node, f"{cmd} 2>/dev/null || true", check=False, timeout=30)
            
            # Clean up network interfaces
            log("  🔌 Cleaning up network interfaces...")
            interfaces = self.ssh_exec(
                node, 
                "ip -o link show | grep -E 'cni|flannel|vxlan.calico|tunl|cilium' | awk -F': ' '{print $2}' | cut -d'@' -f1 2>/dev/null || true",
                check=False
            )
            
            for iface in interfaces.splitlines():
                if iface.strip():
                    log(f"  🔌 Removing interface: {iface}")
                    self.ssh_exec(node, f"sudo ip link delete {iface} 2>/dev/null || true", check=False)
            
            # Clean up mounts
            log("  💾 Cleaning up mounts...")
            mounts = self.ssh_exec(
                node, 
                "mount | grep -E 'kubelet|rke2|containerd' | awk '{print $3}' 2>/dev/null || true",
                check=False
            )
            
            for mount in mounts.splitlines():
                if mount.strip():
                    log(f"  💾 Unmounting: {mount}")
                    self.ssh_exec(node, f"sudo umount {mount} 2>/dev/null || true", check=False)
            
            # Reload systemd and clean up
            log("🔄 Reloading systemd...")
            self.ssh_exec(node, "sudo systemctl daemon-reload || true", check=False, timeout=30)
            self.ssh_exec(node, "sudo systemctl reset-failed || true", check=False, timeout=30)
            
            # Clear kernel modules if they're loaded
            log("🧹 Checking for kernel modules to unload...")
            modules_loaded = self.ssh_exec(
                node, 
                "lsmod | grep -E 'ip_vs_rr|ip_vs_wrr|ip_vs_sh|nf_conntrack' || true",
                check=False
            )
            if modules_loaded.strip():
                log(f"  🧹 Unloading kernel modules...")
                log(f"  📋 Modules found: {modules_loaded.strip()}")
                result = self.ssh_exec(node, "sudo modprobe -r ip_vs_rr ip_vs_wrr ip_vs_sh nf_conntrack 2>&1 || true", check=False)
                if result.strip():
                    log(f"  ℹ️  Module unload output: {result.strip()}")
            
            log("✅ RKE2 reset completed successfully")
            log("✨ Node reset complete!")
            return True
            
        except Exception as e:
            error_msg = f"❌ RKE2 reset failed: {str(e)}\n{traceback.format_exc()}"
            log(error_msg)
            return False
        finally:
            if node.ssh:
                try:
                    node.ssh.close()
                    log("🔌 Closed SSH connection")
                except:
                    pass
                node.ssh = None

    def log(self, node: Node, message: str):
        with open(f"{LOG_DIR}/{node.name}.log", "a") as f:
            f.write(message + "\n")

    def is_rke2_installed(self, node: Node) -> bool:
        """Check if RKE2 is installed on the node.
        
        Args:
            node: The node to check
            
        Returns:
            bool: True if RKE2 is installed, False otherwise
        """
        # Check if RKE2 binary exists
        rke2_exists = self.ssh_exec(
            node,
            "[ -f /usr/local/bin/rke2 ] && echo exists || echo not_exists",
            check=False
        ).strip() == 'exists'
        
        # Check if RKE2 service files exist
        service_exists = self.ssh_exec(
            node,
            "[ -f /usr/local/lib/systemd/system/rke2-*.service ] && echo exists || echo not_exists",
            check=False
        ).strip() == 'exists'
        
        return rke2_exists or service_exists
    
    def is_config_valid(self, node: Node, expected_ip: str) -> bool:
        """Check if the RKE2 config is valid and matches the expected IP.
        
        This method checks:
        1. If the config file exists
        2. If the node-ip matches the expected IP
        3. If bind-address is set correctly
        4. If advertise-address is set correctly
        
        Args:
            node: The node to check
            expected_ip: The expected node IP
            
        Returns:
            bool: True if config is valid, False otherwise
        """
        try:
            self.log(node, f"🔍 Validating RKE2 configuration for IP: {expected_ip}")
            
            # Check if config file exists
            config_exists = self.ssh_exec(
                node,
                "[ -f /etc/rancher/rke2/config.yaml ] && echo exists || echo not_exists",
                check=False
            ).strip() == 'exists'
            
            if not config_exists:
                self.log(node, "❌ RKE2 config file does not exist")
                return False
            
            # Get the complete config for validation
            config_content = self.ssh_exec(
                node,
                "cat /etc/rancher/rke2/config.yaml 2>/dev/null || echo ''",
                check=False
            )
            
            if not config_content.strip():
                self.log(node, "⚠️  RKE2 config file is empty")
                return False
                
            # Check for required fields
            required_fields = [
                ('node-ip', expected_ip),
                ('bind-address', expected_ip),
                ('advertise-address', expected_ip)
            ]
            
            for field, expected_value in required_fields:
                # Get the actual value from the config
                actual_value = self.ssh_exec(
                    node,
                    f"grep -oP '^{field}:\\s*\\K[^\\s]+' /etc/rancher/rke2/config.yaml 2>/dev/null || echo ''",
                    check=False
                ).strip()
                
                if not actual_value:
                    self.log(node, f"⚠️  {field} not found in config")
                    return False
                    
                if actual_value != expected_value:
                    self.log(node, f"❌ {field} mismatch: expected '{expected_value}', got '{actual_value}'")
                    return False
            
            # Check if the node's IP is in the tls-san list if it's a master
            if getattr(node, 'role', '') == 'master':
                tls_san = self.ssh_exec(
                    node,
                    "g -A1 'tls-san:' /etc/rancher/rke2/config.yaml | grep -v 'tls-san:' | grep -v '^--' | tr -d ' -' | tr '\\n' ' ' || echo ''",
                    check=False
                ).strip()
                
                if expected_ip not in tls_san.split():
                    self.log(node, f"❌ Node IP {expected_ip} not found in tls-san list: {tls_san}")
                    return False
            
            self.log(node, "✅ RKE2 configuration is valid")
            return True
            
        except Exception as e:
            self.log(node, f"⚠️  Error validating RKE2 config: {str(e)}")
            return False

    def handle_node(self, node: Node) -> bool:
        """Handle node installation process.
        
        This method orchestrates the complete installation process for a single node,
        including validation, configuration, and installation of RKE2. It's designed
        to be idempotent, meaning it can be safely run multiple times with the same result.
        
        Args:
            node: The node to handle
            
        Returns:
            bool: True if installation was successful or already installed, False otherwise
        """
        node_start_time = time.time()
        self.log(node, "🚀 Starting node setup")
        
        try:
            # 1. Verify SSH connectivity
            if not self.ssh_connect(node):
                self.log(node, "❌ Failed to establish SSH connection")
                return False
                
            # 1.5 Install Cilium CNI if this is a master node (but do this after IP validation)
            # We'll set a flag to install Cilium after we've validated the node's IP
            install_cilium = (node.role == 'master')
            
            # 2. Get and validate node IP
            try:
                # First try to get the configured IP
                ip = self.get_node_ip(node)
                self.log(node, f"🌐 Using configured IP: {ip}")
                
                # Verify the IP is reachable
                try:
                    self.ssh_exec(node, f"ping -c 1 -W 2 {ip} >/dev/null 2>&1 || echo 'UNREACHABLE'", check=False)
                    self.log(node, f"✅ Verified IP {ip} is reachable")
                except Exception as e:
                    self.log(node, f"⚠️  Warning: Could not verify reachability of IP {ip}: {str(e)}")
                
            except Exception as e:
                self.log(node, f"❌ Error with configured node IP: {str(e)}")
                
                # Try to detect the IP from the network interface
                try:
                    self.log(node, "🔍 Attempting to detect node IP from network interfaces...")
                    detected_ip = self.ssh_exec(
                        node,
                        "ip -4 -o addr show | grep -v '127.0.0.1' | awk '{print $4}' | cut -d'/' -f1 | head -1",
                        check=False
                    ).strip()
                    
                    if detected_ip and self._is_valid_ip(detected_ip):
                        self.log(node, f"🌐 Detected IP from network interface: {detected_ip}")
                        node.ip = detected_ip
                        ip = detected_ip
                    else:
                        error_msg = f"❌ Could not detect valid IP from network interfaces: {detected_ip}"
                        self.log(node, error_msg)
                        raise Exception(error_msg)
                        
                except Exception as detect_error:
                    error_msg = f"❌ Failed to detect node IP: {str(detect_error)}"
                    self.log(node, error_msg)
                    raise Exception(error_msg)
            
            # Update the node's IP in the configuration
            node.ip = ip
            self.log(node, f"🌐 Node IP set to: {ip}")
            
            # Now that we have a valid IP, install Cilium if needed
            if install_cilium:
                self.log(node, "🔧 Installing Cilium CNI...")
                if not self.install_cilium_cni(node):
                    self.log(node, "⚠️  Failed to install Cilium CNI, but continuing with installation")
            
            # 3. Check if RKE2 is already installed and running
            service_name = f"rke2-{'server' if node.role == 'master' else 'agent'}"
            is_running, status = self._check_service_status(node, service_name)
            
            # 4. Check if configuration is valid
            config_valid = self.is_config_valid(node, ip)
            
            # 5. Handle different states
            if is_running:
                if config_valid:
                    self.log(node, f"✅ RKE2 is already running with valid configuration")
                    return True
                else:
                    self.log(node, "⚠️  RKE2 is running but configuration is invalid. Reconfiguring...")
                    self.reset_rke2(node)
                    return self._install_rke2_attempt(node, node.role, service_name)
            else:
                # RKE2 is not running, install it
                self.log(node, f"🔄 RKE2 is not running. Starting installation...")
                return self.install_rke2(node)
                
        except Exception as e:
            self.log(node, f"❌ Error during node setup: {str(e)}")
            return False

    def validate_cluster(self, max_retries: int = 10, retry_delay: int = 10):
        """Validate the cluster is healthy by checking the API endpoint.
        
        Args:
            max_retries: Maximum number of retry attempts
            retry_delay: Delay between retries in seconds
        """
        import time
        from datetime import datetime, timedelta
        
        start_time = datetime.now()
        last_error = None
        
        for attempt in range(1, max_retries + 1):
            try:
                # Try to get API status
                out = subprocess.check_output(
                    ["curl", "-sk", f"https://{self.bootstrap_ip}:9345/ping"],
                    timeout=5,
                    stderr=subprocess.PIPE
                )
                status = out.decode().strip()
                elapsed = (datetime.now() - start_time).total_seconds()
                print(f"✅ Cluster API is healthy after {elapsed:.1f}s: {status}")
                return True
                
            except subprocess.CalledProcessError as e:
                last_error = e
                status = e.stderr.decode().strip() or str(e)
            except Exception as e:
                last_error = e
                status = str(e)
                
            elapsed = (datetime.now() - start_time).total_seconds()
            if attempt < max_retries:
                print(f"⏳ Waiting for cluster API to be ready (attempt {attempt}/{max_retries}, {elapsed:.1f}s): {status}")
                time.sleep(retry_delay)
            else:
                print(f"❌ Failed to validate cluster after {max_retries} attempts ({elapsed:.1f}s): {status}")
                if last_error:
                    print(f"Last error details: {last_error}")
                return False

    def status(self):
        for node in self.nodes:
            if self.ssh_connect(node):
                ip = self.get_node_ip(node)
                status = self.ssh_exec(node, "sudo systemctl is-active rke2-server || sudo systemctl is-active rke2-agent")
                self.log(node, f"[STATUS] {node.name} IP={ip}, RKE2={status}")

    def run(self, validate: bool = True) -> bool:
        """Run the RKE2 installation on all nodes.
        
        This method orchestrates the complete installation process across all nodes,
        handling parallel execution, error handling, and cluster validation.
        
        Args:
            validate: If True, validate the cluster after installation
            
        Returns:
            bool: True if all nodes were processed successfully, False otherwise
        """
        import traceback
        start_time = time.time()
        print("\n" + "="*80)
        print("🚀 Starting RKE2 Cluster Deployment")
        print("="*80)
        print(f"📋 Processing {len(self.nodes)} nodes in batches of 10")
        
        # Track installation results
        success_count = 0
        total_nodes = len(self.nodes)
        node_results = {}
        
        # Process nodes in batches to avoid overwhelming the system
        for batch_num, chunk in enumerate(self.batch(self.nodes, 10), 1):
            batch_start = time.time()
            chunk = [n for n in chunk if n.name not in node_results]  # Skip already processed nodes
            if not chunk:
                print(f"\n🔄 Batch {batch_num}: All nodes already processed, skipping...")
                continue
                
            print(f"\n🔄 Processing batch {batch_num} with {len(chunk)} nodes...")
            
            with ThreadPoolExecutor(max_workers=min(10, len(chunk))) as pool:
                # Process nodes in parallel with progress tracking
                future_to_node = {}
                for node in chunk:
                    print(f"  🚦 Queueing {node.name} ({node.role}) for processing...")
                    future = pool.submit(self.handle_node, node)
                    future_to_node[future] = node
                
                # Process results as they complete
                completed = 0
                for future in future_to_node:
                    node = future_to_node[future]
                    try:
                        print(f"  ⏳ Waiting for {node.name} to complete...")
                        success = future.result(timeout=300)  # 5 minute timeout per node
                        node_results[node.name] = success
                        status = "✅ Succeeded" if success else "❌ Failed"
                        print(f"  {status} - {node.name} ({node.role})")
                        
                        if success:
                            success_count += 1
                        else:
                            print(f"     Check logs at: {LOG_DIR}/{node.name}.log")
                        
                        completed += 1
                        print(f"  📊 Progress: {completed}/{len(chunk)} nodes in current batch")
                            
                    except Exception as e:
                        node_results[node.name] = False
                        print(f"❌ Error processing {node.name}: {str(e)}")
                        print("Traceback:", traceback.format_exc())
                        print(f"     Check logs at: {LOG_DIR}/{node.name}.log")
                        completed += 1
            
            # Log batch completion
            batch_elapsed = time.time() - batch_start
            batch_success = sum(1 for n in chunk if node_results.get(n.name, False))
            print(f"\n📦 Batch {batch_num} completed in {batch_elapsed/60:.1f} minutes")
            print(f"   Success: {batch_success}/{len(chunk)}")
            
            # Print current status after each batch
            print("\n📋 Current Status:" + "-"*60)
            for node in sorted(self.nodes, key=lambda n: (not node_results.get(n.name, False), n.role, n.name)):
                status = "✅" if node_results.get(node.name) else "❌"
                print(f"{status} {node.name:20} {node.role:8} {node.ip}")
            print("-"*70 + "\n")
        
        # Print final summary
        total_elapsed = time.time() - start_time
        print("\n" + "="*80)
        print("📊 Deployment Summary")
        print("="*80)
        
        # Print node status
        for node in sorted(self.nodes, key=lambda n: (not node_results.get(n.name, False), n.role, n.name)):
            status = "✅" if node_results.get(node.name) else "❌"
            print(f"{status} {node.name:20} {node.role:8} {node.ip}")
        
        # Print overall status
        print(f"\n💡 Successfully processed {success_count}/{total_nodes} nodes")
        print(f"⏱️  Total time: {total_elapsed/60:.1f} minutes")
        
        # Validate cluster if requested and we had some successful installations
        cluster_valid = False
        if validate and success_count > 0:
            print("\n🔍 Validating cluster health...")
            try:
                cluster_valid = self.validate_cluster()
                if cluster_valid:
                    print("\n✅ Cluster is healthy and ready to use!")
                else:
                    print("\n⚠️  Cluster validation failed. The cluster may still be initializing.")
            except Exception as e:
                print(f"\n⚠️  Error during cluster validation: {str(e)}")
                traceback.print_exc()
                cluster_valid = False
            
            if not cluster_valid:
                print("   You can check the status manually with: kubectl get nodes")
        
        # Final status
        all_success = success_count == total_nodes
        if all_success and (not validate or cluster_valid):
            print("\n🎉 Deployment completed successfully!")
            return True
        else:
            if not all_success:
                print(f"\n⚠️  Deployment completed with {total_nodes - success_count} failures.")
            if validate and not cluster_valid:
                print("   Cluster validation failed.")
            return False

    def _check_node_reachable(self, node: Node) -> bool:
        """Check if a node is reachable via SSH.
        
        Args:
            node: The node to check
            
        Returns:
            bool: True if node is reachable, False otherwise
        """
        try:
            return self.ssh_connect(node)
        except Exception as e:
            self.log(node, f"❌ Node is not reachable: {str(e)}")
            return False
            
    def ssh_connect(self, node: Node) -> bool:
        """Establish an SSH connection to the node with retries and increased timeout.
        
        Args:
            node: The node to connect to
            
        Returns:
            bool: True if connection was successful, False otherwise
        """
        max_retries = 3
        for attempt in range(1, max_retries + 1):
            try:
                if hasattr(node, 'ssh') and node.ssh is not None:
                    # Test if existing connection is still alive
                    try:
                        transport = node.ssh.get_transport()
                        if transport and transport.is_active():
                            # Send a keepalive to check connection
                            transport.send_ignore()
                            return True
                    except:
                        # Connection is dead, close and reconnect
                        try:
                            node.ssh.close()
                        except:
                            pass
                        node.ssh = None
                
                # Create new connection
                key = paramiko.RSAKey.from_private_key_file(self.ssh_key_path)
                client = paramiko.SSHClient()
                client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                # Increased timeout and added banner timeout
                client.connect(
                    node.ip, 
                    username=self.ssh_user, 
                    pkey=key, 
                    timeout=30, 
                    banner_timeout=30,
                    auth_timeout=30
                )
                node.ssh = client
                return True
                
            except Exception as e:
                self.log(node, f"[SSH CONNECTION ATTEMPT {attempt}/{max_retries}] {str(e)}")
                if attempt == max_retries:
                    self.log(node, f"❌ All SSH connection attempts failed for {node.ip}")
                    return False
                time.sleep(5)  # Wait before retry
        return False
        
    def monitor_logs(self, node: Node, service_name: str, duration: int = 30) -> None:
        """Monitor RKE2 service logs in the background.
        
        Args:
            node: The node to monitor
            service_name: Name of the service to monitor (rke2-server or rke2-agent)
            duration: How long to monitor logs in seconds
        """
        try:
            import time
            from datetime import datetime
            
            log_file = os.path.join(LOG_DIR, f"{node.name}-{service_name}.log")
            end_time = time.time() + duration
            
            # Start a background thread to monitor logs
            def _monitor():
                try:
                    with open(log_file, 'a') as f:
                        f.write(f"\n=== Starting log monitor at {datetime.now()} ===\n")
                        f.flush()
                        
                        while time.time() < end_time:
                            # Get the last 20 lines of journalctl
                            cmd = f"sudo journalctl -u {service_name} --no-pager -n 20 --since '1 minute ago'"
                            _, stdout, _ = self.ssh_exec(node, cmd, check=False, get_pty=True)
                            
                            if stdout.strip():
                                f.write(f"\n[{datetime.now()}] {service_name} logs:\n")
                                f.write(stdout)
                                f.flush()
                            
                            time.sleep(5)  # Check logs every 5 seconds
                            
                except Exception as e:
                    with open(log_file, 'a') as f:
                        f.write(f"\n[ERROR] Log monitor failed: {str(e)}\n")
            
            # Start the monitor thread
            import threading
            monitor_thread = threading.Thread(target=_monitor, daemon=True)
            monitor_thread.start()
            return monitor_thread
            
        except Exception as e:
            self.log(node, f"❌ Failed to start log monitor: {str(e)}")
            return None
            
    def reset_rke2(self, node: Node) -> bool:
        """Reset RKE2 on a single node using the RKE2Reset class.
        
        This method:
        1. Starts log monitoring
        2. Uses RKE2Reset to clean up the node
        3. Reinstalls RKE2 for a clean state
        
        Args:
            node: The node to reset
            
        Returns:
            bool: True if reset was successful, False otherwise
        """
        from infractl.modules.rke2.reset import RKE2Reset
        from infractl.modules.connection import ConnectionPool
        from infractl.modules.rke2.models import Node as RKE2Node
        
        service_name = f"rke2-{'server' if node.role == 'master' else 'agent'}"
        log_file = os.path.join(LOG_DIR, f"{node.name}-reset.log")
        
        def log(msg: str) -> None:
            """Helper to log messages to both console and log file"""
            timestamp = datetime.now().strftime("%H:%M:%S")
            log_msg = f"[{timestamp}] {msg}"
            print(f"  {log_msg}")
            with open(log_file, 'a') as f:
                f.write(f"{log_msg}\n")
        
        try:
            # Start log monitoring in background
            log("🔄 Starting RKE2 reset...")
            monitor_thread = self.monitor_logs(node, service_name, duration=300)  # Monitor for 5 minutes
            
            try:
                # Create a connection pool and RKE2 node object
                connection_pool = ConnectionPool()
                rke2_node = RKE2Node(
                    name=node.name,
                    ip=node.ip,
                    role=node.role,
                    ssh_key_path=self.ssh_key_path,  # Fixed attribute name
                    ssh_user=self.ssh_user
                )
                
                # Use RKE2Reset to clean up the node
                log("🧹 Cleaning up RKE2 installation...")
                reset_handler = RKE2Reset(connection_pool)
                if not reset_handler.reset_node(rke2_node, is_server=(node.role == 'master')):
                    log("⚠️  Some cleanup operations may have failed, but continuing with reinstallation...")
                
                # Reinstall RKE2 to ensure clean state
                log("🔄 Reinstalling RKE2...")
                try:
                    # Download and install RKE2
                    self.ssh_exec(node, "curl -sfL https://get.rke2.io | sudo sh - 2>/dev/null || true", check=False)
                    
                    # Re-enable and start the service
                    log("🔄 Enabling and starting RKE2 service...")
                    self.ssh_exec(node, f"sudo systemctl enable {service_name} 2>/dev/null || true", check=False)
                    
                    # Verify installation
                    result = self.ssh_exec(node, "command -v rke2 2>/dev/null || echo 'not found'", check=False)
                    if 'not found' in result[1]:
                        log("❌ RKE2 installation verification failed")
                        return False
                        
                    log("✅ RKE2 reset and reinstallation completed successfully")
                    return True
                    
                except Exception as e:
                    log(f"❌ Failed to reinstall RKE2: {str(e)}")
                    return False
                
            except Exception as e:
                log(f"❌ Failed to reset RKE2: {str(e)}")
                return False
                
            finally:
                # Ensure log monitor is stopped
                if monitor_thread and monitor_thread.is_alive():
                    monitor_thread.join(timeout=5)
                    
        except Exception as e:
            log(f"❌ Unexpected error during reset: {str(e)}")
            return False
            
    def reset(self, skip_checks: bool = False) -> bool:
        """Reset RKE2 on all nodes in parallel.
        
        Args:
            skip_checks: If True, skip node reachability checks
            
        Returns:
            bool: True if reset was successful on all nodes, False otherwise
        """
        import time
        from concurrent.futures import ThreadPoolExecutor, as_completed
        
        start_time = time.time()
        print("\n" + "="*80)
        print("🔄 Starting RKE2 Cluster Reset")
        print("="*80)
        
        total_nodes = len(self.nodes)
        success_count = 0
        node_results = {}
        
        # Process nodes in batches to avoid overwhelming the system
        for batch_num, chunk in enumerate(self.batch(self.nodes, 10), 1):
            batch_start = time.time()
            chunk = [n for n in chunk if n.name not in node_results]  # Skip already processed nodes
            if not chunk:
                print(f"\n🔄 Batch {batch_num}: All nodes already processed, skipping...")
                continue
                
            print(f"\n🔄 Processing reset batch {batch_num} with {len(chunk)} nodes...")
            
            with ThreadPoolExecutor(max_workers=len(chunk)) as pool:  # Use one worker per node in batch
                # First, submit all tasks
                future_to_node = {}
                nodes_to_process = []
                
                for node in chunk:
                    if not skip_checks and not self._check_node_reachable(node):
                        print(f"  ⚠️  Node {node.name} not reachable, skipping reset")
                        node_results[node.name] = False
                        continue
                        
                    print(f"  🚦 Queueing reset for {node.name} ({node.role})...")
                    future = pool.submit(self.reset_rke2, node)
                    future_to_node[future] = node
                    nodes_to_process.append(node)
                
                # Start all tasks before waiting for any to complete
                reset_start_time = time.time()
                print(f"  🚀 Started {len(nodes_to_process)} parallel reset operations...")
                
                # Process results as they complete
                completed = 0
                for future in as_completed(future_to_node):
                    node = future_to_node[future]
                    try:
                        success = future.result()
                        node_results[node.name] = success
                        status = "✅ Succeeded" if success else "❌ Failed"
                        elapsed = time.time() - reset_start_time
                        print(f"  {status} - {node.name} ({node.role}) in {elapsed:.1f}s")
                        
                        if success:
                            success_count += 1
                        else:
                            print(f"     Check logs at: {LOG_DIR}/{node.name}.log")
                        
                        completed += 1
                        print(f"  📊 Progress: {completed}/{len(nodes_to_process)} nodes in current batch")
                                
                    except Exception as e:
                        node_results[node.name] = False
                        print(f"❌ Error resetting {node.name}: {str(e)}")
                        print("Traceback:", traceback.format_exc())
                        print(f"     Check logs at: {LOG_DIR}/{node.name}.log")
                        completed += 1
            
            # Log batch completion
            batch_elapsed = time.time() - batch_start
            batch_success = sum(1 for n in chunk if node_results.get(n.name, False))
            print(f"\n📦 Reset batch {batch_num} completed in {batch_elapsed/60:.1f} minutes")
            print(f"   Success: {batch_success}/{len(chunk)}")
            
            # Print current status after each batch
            print("\n📋 Current Status:" + "-"*60)
            for node in sorted(self.nodes, key=lambda n: (not node_results.get(n.name, False), n.role, n.name)):
                status = "✅" if node_results.get(node.name, False) else "❌"
                print(f"{status} {node.name:20} {node.role:8} {node.ip}")
            print("-"*70 + "\n")
        
        # Print final summary
        total_elapsed = time.time() - start_time
        print("\n" + "="*80)
        print("📊 Reset Summary")
        print("="*80)
        
        # Print node status
        for node in sorted(self.nodes, key=lambda n: (not node_results.get(n.name, False), n.role, n.name)):
            status = "✅" if node_results.get(node.name, False) else "❌"
            print(f"{status} {node.name:20} {node.role:8} {node.ip}")
        
        # Print overall status
        print(f"\n💡 Successfully reset {success_count}/{total_nodes} nodes")
        print(f"⏱️  Total time: {total_elapsed/60:.1f} minutes")
        
        # Final status
        all_success = success_count == total_nodes
        if all_success:
            print("\n🎉 Reset completed successfully!")
        else:
            print(f"\n⚠️  Reset completed with {total_nodes - success_count} failures.")
            
        return all_success

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python install_rke2_scalable.py <cluster.yaml> <run|reset|status> [--dry-run]")
        sys.exit(1)

    mode = sys.argv[2]
    dry_run = "--dry-run" in sys.argv

    installer = RKE2Installer(sys.argv[1], dry_run=dry_run)
    if mode == "run":
        installer.run()
    elif mode == "reset":
        installer.reset()
    elif mode == "status":
        installer.status()
    else:
        print(f"Unknown mode: {mode}")
        sys.exit(1)
