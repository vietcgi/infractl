"""RKE2 service management.

This module handles RKE2 service lifecycle operations.
"""

import logging
import os
import re
import shlex
import subprocess
import time
from typing import Dict, Any, List, Optional, Tuple

from ..models import Node
from .configuration import render_config, write_node_config

# Get the directory where this module is located
MODULE_DIR = os.path.dirname(os.path.abspath(__file__))

logger = logging.getLogger("rke2.installer.service")

def is_rke2_installed(installer, node: Node) -> bool:
    """Check if RKE2 is already installed and running on the node in an idempotent way.
    
    This function performs multiple checks to ensure RKE2 is fully installed and running:
    1. Checks if RKE2 binary exists
    2. Verifies the correct service is installed and enabled
    3. Checks if the service is active
    4. Verifies the kubelet is running
    
    Args:
        installer: RKE2Installer instance
        node: Node to check
        
    Returns:
        bool: True if RKE2 is properly installed and running, False otherwise
    """
    try:
        logger.debug(f"[DEBUG] Starting RKE2 installation check on {node.name}")
        
        # Check if RKE2 binary exists
        logger.debug(f"[DEBUG] Checking if RKE2 binary exists on {node.name}")
        rke2_bin = installer._ssh_exec(node, 'command -v rke2 2>/dev/null || echo "not found"').strip()
        logger.debug(f"[DEBUG] RKE2 binary check result on {node.name}: {rke2_bin}")
        
        if rke2_bin == 'not found':
            logger.debug(f"[DEBUG] RKE2 binary not found on {node.name}")
            return False
            
        # Check if service is installed and enabled
        service_name = 'rke2-server.service' if node.role == 'master' else 'rke2-agent.service'
        logger.debug(f"[DEBUG] Checking service {service_name} on {node.name}")
        
        # Check if service exists
        service_exists_cmd = f'systemctl list-unit-files | grep -q "^{service_name}\\s" && echo "exists" || echo "not found"'
        service_exists = installer._ssh_exec(node, service_exists_cmd).strip()
        logger.debug(f"[DEBUG] Service {service_name} exists check on {node.name}: {service_exists}")
        
        if service_exists != 'exists':
            logger.debug(f"[DEBUG] Service {service_name} not found on {node.name}")
            return False
            
        # Check if service is enabled
        service_enabled_cmd = f'systemctl is-enabled {service_name} 2>/dev/null || echo "disabled"'
        service_enabled = installer._ssh_exec(node, service_enabled_cmd).strip()
        logger.debug(f"[DEBUG] Service {service_name} enabled check on {node.name}: {service_enabled}")
        
        if service_enabled == 'disabled':
            logger.debug(f"[DEBUG] Service {service_name} is not enabled on {node.name}")
            return False
            
        # Check if service is active
        logger.debug(f"[DEBUG] Checking if service {service_name} is active on {node.name}")
        service_active_cmd = f'systemctl is-active {service_name} 2>/dev/null || echo "inactive"'
        service_active = installer._ssh_exec(node, service_active_cmd).strip()
        logger.debug(f"[DEBUG] Service {service_name} active check on {node.name}: {service_active}")
        
        if service_active != 'active':
            logger.debug(f"[DEBUG] Service {service_name} is not active on {node.name}")
            return False
            
        # Check if kubelet is running
        logger.debug(f"[DEBUG] Checking if kubelet is running on {node.name}")
        kubelet_check_cmd = 'pgrep -f kubelet >/dev/null 2>&1 && echo "running" || echo "not running"'
        kubelet_running = installer._ssh_exec(node, kubelet_check_cmd).strip()
        logger.debug(f"[DEBUG] Kubelet running check on {node.name}: {kubelet_running}")
        
        if kubelet_running != 'running':
            logger.debug(f"[DEBUG] Kubelet is not running on {node.name}")
            return False
            
        logger.debug(f"[DEBUG] All RKE2 installation checks passed on {node.name}")
        return True
        
    except Exception as e:
        logger.debug(f"[DEBUG] RKE2 installation check failed on {node.name}: {str(e)}", exc_info=True)
        return False

def install_rke2(installer, node: Node, is_server: bool = True, kubernetes_version: str = None) -> None:
    """Install RKE2 on a node in an idempotent way.
    
    This function ensures RKE2 is properly installed and configured. It is safe to run
    multiple times as it checks the current state before making any changes.
    
    Args:
        installer: RKE2Installer instance
        node: Node to install RKE2 on
        is_server: Whether this is a server or agent installation
        kubernetes_version: Kubernetes version to install (e.g., 'v1.25.16+rke2r1')
        
    Raises:
        RuntimeError: If installation fails
    """
    logger.debug(f'[DEBUG] Starting RKE2 installation on {node.name} (server: {is_server})')
    
    # Default to a stable version if not specified
    if not kubernetes_version:
        kubernetes_version = 'v1.25.16+rke2r1'
    logger.debug(f'[DEBUG] Using Kubernetes version: {kubernetes_version}')
    
    # Check if RKE2 is already installed and running
    logger.debug(f'[DEBUG] Checking if RKE2 is already installed on {node.name}...')
    if is_rke2_installed(installer, node):
        logger.info(f'✅ RKE2 is already installed and running on {node.name}')
        return
    logger.debug(f'[DEBUG] RKE2 not found installed on {node.name}, proceeding with installation')
    
    logger.info(f'📦 Installing RKE2 on {node.name}...')
    
    try:
        logger.debug(f'[DEBUG] Starting RKE2 installation process on {node.name}')
        
        # Ensure the system is prepared for installation
        logger.debug(f'[DEBUG] Preparing system for RKE2 installation on {node.name}')
        _prepare_system(installer, node)
        logger.debug(f'[DEBUG] System preparation completed on {node.name}')
        
        # Install RKE2 using the official installation script
        logger.debug(f'[DEBUG] Installing RKE2 binary on {node.name}')
        _install_rke2_binary(installer, node, is_server, kubernetes_version)
        logger.debug(f'[DEBUG] RKE2 binary installation completed on {node.name}')
        
        # Configure RKE2 service
        logger.debug(f'[DEBUG] Configuring RKE2 service on {node.name}')
        _configure_rke2_service(installer, node, is_server)
        logger.debug(f'[DEBUG] RKE2 service configuration completed on {node.name}')
        
        logger.info(f'✅ Successfully installed RKE2 on {node.name}')
        
    except Exception as e:
        error_msg = f'Failed to install RKE2 on {node.name}: {str(e)}'
        logger.error(error_msg, exc_info=True)
        raise RuntimeError(error_msg) from e

def _prepare_system(installer, node: Node) -> None:
    """Prepare the system for RKE2 installation in an idempotent way."""
    # Create necessary directories with proper permissions (idempotent)
    dirs = [
        '/etc/rancher/rke2',
        '/var/lib/rancher/rke2/server/manifests',
        '/var/lib/rancher/rke2/agent',
        '/var/lib/kubelet/volumeplugins'
    ]
    
    logger.debug("[%s] Preparing system directories for RKE2 installation", node.name)
    
    for dir_path in dirs:
        logger.debug("[%s] Creating directory: %s", node.name, dir_path)
        try:
            # First check if directory exists and has correct permissions
            check_cmd = f'if [ -d "{dir_path}" ]; then stat -c "%a" "{dir_path}"; fi'
            result = installer._ssh_exec(node, check_cmd, check=False)
            
            if result and result.strip().isdigit():
                mode = int(result.strip())
                if mode == 0o755:
                    logger.debug("[%s] Directory %s already exists with correct permissions (755)", node.name, dir_path)
                    continue
                else:
                    logger.debug("[%s] Directory %s exists with mode %o, will update permissions", 
                                node.name, dir_path, mode)
            
            # Create directory and set permissions
            installer._ssh_exec(
                node,
                f'sudo mkdir -p {dir_path} && sudo chmod 755 {dir_path}',
                check=True
            )
            logger.debug("[%s] Successfully created/updated directory: %s", node.name, dir_path)
            
        except Exception as e:
            logger.error(
                "[%s] Failed to create/setup directory %s: %s",
                node.name, dir_path, str(e),
                exc_info=True
            )
            raise
    
    # Ensure required kernel modules are loaded
    installer._ssh_exec(
        node,
        'for mod in br_netfilter ip6_udp_tunnel ip_set ip_set_hash_ip ip_set_hash_net iptable_filter iptable_nat iptable_mangle iptable_raw nf_conntrack_netlink nf_conntrack nf_nat nf_nat_masquerade_ipv4 nf_nat_masquerade_ipv6 overlay tun veth vxlan x_tables xt_addrtype xt_conntrack xt_comment xt_mark xt_multiport xt_nat xt_recent xt_set xt_statistic xt_tcpudp; do '
        '  sudo modprobe $mod 2>/dev/null || true; '
        'done',
        check=False
    )
    
def _install_rke2_binary(installer, node: Node, is_server: bool, kubernetes_version: str) -> None:
    """Install RKE2 binary in an idempotent way.
    
    Args:
        installer: RKE2Installer instance
        node: Node to install RKE2 on
        is_server: Whether this is a server or agent installation
        kubernetes_version: Kubernetes version to install (e.g., 'v1.25.16+rke2r1')
    """
    import hashlib
    max_retries = 3
    retry_delay = 5  # seconds
    
    logger.info(f'🔍 Checking if RKE2 is already installed on {node.name}...')
    try:
        # More thorough check for existing installation
        rke2_bin = installer._ssh_exec(node, 'command -v rke2 2>/dev/null || echo "not_found"', check=False).strip()
        if rke2_bin != 'not_found':
            rke2_version = installer._ssh_exec(node, f'sudo {rke2_bin} --version 2>/dev/null || echo "version_unknown"', check=False).strip()
            logger.info(f'✅ RKE2 binary already installed on {node.name}: {rke2_version}')
            return
        logger.info('ℹ️  No existing RKE2 installation found, proceeding with installation')
    except Exception as e:
        logger.warning(f'⚠️  Error checking for existing RKE2 installation on {node.name}: {str(e)}')
    
    # Validate and parse Kubernetes version
    try:
        logger.info(f'🔧 Validating Kubernetes version: {kubernetes_version}')
        version_parts = kubernetes_version.lstrip('v').split('.')
        if len(version_parts) < 2:
            raise ValueError(f'Invalid version format: {kubernetes_version}. Expected format: vX.Y.Z+rke2rN')
            
        channel = f"v{version_parts[0]}.{version_parts[1]}"
        logger.info(f'🚀 Installing RKE2 {kubernetes_version} (channel: {channel}) on {node.name}...')
        
        # Prepare installation environment variables
        install_vars = [
            f'INSTALL_RKE2_CHANNEL={channel}',
            f'INSTALL_RKE2_VERSION={kubernetes_version}'
        ]
        if not is_server:
            install_vars.append('INSTALL_RKE2_TYPE=agent')
        install_vars_str = ' '.join(install_vars)
        
        # Enhanced installation script with detailed logging
        install_script = f'''
set -ex

echo "=== Starting RKE2 installation on $(hostname) ==="
echo "Installation type: {'server' if is_server else 'agent'}"
echo "Kubernetes version: {kubernetes_version}"
echo "Installation channel: {channel}"

# Create temporary directory for installation files
TMP_DIR=$(mktemp -d)
trap 'rm -rf "$TMP_DIR"' EXIT

echo "=== Checking system requirements ==="
# Check kernel modules
for mod in br_netfilter overlay; do
    if ! grep -q "^$mod" /proc/modules; then
        echo "⚠️  Kernel module $mod is not loaded"
        echo "Attempting to load $mod..."
        sudo modprobe $mod || echo "⚠️  Failed to load $mod"
    fi
done

# Check systemd version
systemd_version=$(systemctl --version | head -1 | cut -d' ' -f2)
echo "Systemd version: $systemd_version"

# Check for existing RKE2 processes
if pgrep -f rke2 >/dev/null; then
    echo "⚠️  Found existing RKE2 processes. Attempting to stop them..."
    sudo pkill -f rke2 || true
    sleep 2
fi

echo "=== Downloading RKE2 installation script ==="
TMP_SCRIPT="$TMP_DIR/install.sh"
for i in {{1..3}}; do
    echo "Download attempt $i/3..."
    if curl -sfL https://get.rke2.io -o "$TMP_SCRIPT"; then
        echo "✅ Successfully downloaded RKE2 installation script"
        # Verify script is not empty and is executable
        if [ -s "$TMP_SCRIPT" ] && [ -x "$TMP_SCRIPT" ]; then
            echo "✅ Script is valid and executable"
            break
        else
            echo "❌ Downloaded script is invalid"
            if [ $i -eq 3 ]; then
                echo "❌ Failed to download valid script after 3 attempts"
                exit 1
            fi
        fi
    fi
    echo "❌ Download failed, retrying in $((i * 2)) seconds..."
    sleep $((i * 2))
done

# Run the installation with verbose output
echo "=== Installing RKE2 ==="
chmod +x "$TMP_SCRIPT"
sudo {install_vars_str} "$TMP_SCRIPT"

# Verify installation
echo "=== Verifying installation ==="
if command -v rke2 >/dev/null 2>&1; then
    RKE2_BIN=$(command -v rke2)
    echo "✅ RKE2 binary found at: $RKE2_BIN"
    echo "RKE2 version: $($RKE2_BIN --version 2>&1 || echo 'version check failed')"
else
    echo "❌ RKE2 binary not found in PATH"
    echo "Current PATH: $PATH"
    echo "Checking common locations..."
    for path in /usr/local/bin/rke2 /var/lib/rancher/rke2/bin/rke2; do
        if [ -x "$path" ]; then
            echo "Found RKE2 at $path"
            RKE2_BIN="$path"
            break
        fi
done
    if [ -z "$RKE2_BIN" ]; then
        echo "❌ Could not find RKE2 binary after installation"
        exit 1
    fi
fi

echo "=== Installation completed successfully ==="
'''
        
        logger.debug(f'Running enhanced installation script on {node.name} with vars: {install_vars}')
        
        for attempt in range(1, max_retries + 1):
            try:
                logger.info(f'🚀 Attempt {attempt}/{max_retries} - Installing RKE2 on {node.name}...')
                
                # Increase timeout to 10 minutes for the installation
                output = installer._ssh_exec(
                    node,
                    install_script,
                    check=True,
                    command_timeout=600,  # 10 minutes timeout for installation
                    use_sudo=True
                )
                
                # Log the full output for debugging
                logger.debug(f'RKE2 installation output from {node.name}:\n{output}')
                
                # Verify the installation was successful
                verify_cmd = 'command -v rke2 >/dev/null 2>&1 && echo "INSTALLED" || echo "NOT_INSTALLED"'
                if installer._ssh_exec(node, verify_cmd).strip() != 'INSTALLED':
                    raise RuntimeError('RKE2 binary not found after installation')
                
                logger.info(f'✅ Successfully installed RKE2 on {node.name}')
                break
                
            except Exception as e:
                if attempt == max_retries:
                    logger.error(f'❌ Failed to install RKE2 on {node.name} after {max_retries} attempts')
                    logger.error(f'Error: {str(e)}')
                    logger.error(f'Installation output:\n{getattr(e, "output", "No output")}')
                    
                    # Gather additional debug information
                    try:
                        logger.info('Gathering system information for debugging...')
                        debug_info = installer._ssh_exec(
                            node,
                            'echo "=== System Info ===" && '
                            'uname -a && echo "\n=== Disk Space ===" && '
                            'df -h && echo "\n=== Memory ===" && '
                            'free -h && echo "\n=== CPU Info ===" && '
                            'lscpu | grep -E "^CPU\(s\)|Thread|Socket|Core" && '
                            'echo "\n=== Kernel Modules ===" && '
                            'lsmod | grep -E "br_netfilter|overlay|ip_vs|ip_vs_rr|ip_vs_wrr|ip_vs_sh|nf_conntrack"',
                            check=False
                        )
                        logger.debug(f'System information from {node.name}:\n{debug_info}')
                    except Exception as debug_err:
                        logger.warning(f'Failed to gather debug info: {str(debug_err)}')
                    
                    raise
                
                wait_time = retry_delay * attempt
                logger.warning(
                    f'⚠️  Attempt {attempt}/{max_retries} failed. Retrying in {wait_time} seconds...\n'
                    f'Error: {str(e)}'
                )
                time.sleep(wait_time)
        
        # Only proceed with Cilium manifest if this is the bootstrap server
        if is_server and hasattr(installer, 'bootstrap_ip') and installer.bootstrap_ip == node.ip:
            logger.info('🔄 Configuring Cilium manifest on bootstrap server...')
            _ensure_cilium_manifest(installer, node)
            
    except Exception as e:
        error_msg = f'Failed to install RKE2 on {node.name}: {str(e)}'
        logger.error(f'❌ {error_msg}', exc_info=True)
        raise RuntimeError(error_msg) from e

def _get_node_config(installer, node: Node, is_server: bool) -> Dict[str, Any]:
    """Generate node configuration using Jinja2 template.
    
    Args:
        installer: RKE2Installer instance
        node: Node to generate config for
        is_server: Whether this is a server node
        
    Returns:
        dict: Generated node configuration
    """
    # Determine if this is the bootstrap node
    is_bootstrap = is_server and (not hasattr(installer, 'bootstrap_ip') or installer.bootstrap_ip == node.ip)
    bootstrap_ip = None if is_bootstrap else getattr(installer, 'bootstrap_ip', None)
    
    # Render the configuration from template
    config_yaml = render_config(
        node=node,
        cluster_token=installer.cluster_token,
        is_server=is_server,
        is_bootstrap=is_bootstrap,
        bootstrap_ip=bootstrap_ip
    )
    
    # Convert YAML to dict
    import yaml
    return yaml.safe_load(config_yaml)

def _configure_rke2_service(installer, node: Node, is_server: bool) -> None:
    """Configure RKE2 service using template-based configuration.
    
    Args:
        installer: RKE2Installer instance
        node: Node to configure
        is_server: Whether this is a server node
    """
    service_name = 'rke2-server' if is_server else 'rke2-agent'
    
    # Determine if this is the bootstrap node
    is_bootstrap = False
    if is_server:
        if not hasattr(installer, 'bootstrap_ip'):
            installer.bootstrap_ip = node.ip
            is_bootstrap = True
            installer.log(node, f"🔧 Configuring as bootstrap node with IP: {node.ip}")
        else:
            is_bootstrap = (installer.bootstrap_ip == node.ip)
            if not is_bootstrap:
                installer.log(node, f"🔧 Configuring as additional server joining bootstrap at: {installer.bootstrap_ip}")
    
    # Generate and write the configuration
    try:
        config = _get_node_config(installer, node, is_server)
        write_node_config(installer, node, config)
        installer.log(node, f"✅ RKE2 configuration applied successfully")
    except Exception as e:
        installer.log(node, f"❌ Failed to write RKE2 configuration: {str(e)}")
        raise
    
    # Enable and reload the service
    installer._ssh_exec(
        node,
        f'sudo systemctl enable {service_name} && sudo systemctl daemon-reload',
        check=True
    )

def _ensure_cilium_manifest(installer, node: Node) -> None:
    """Ensure Cilium manifest is properly installed on the node.
    
    Args:
        installer: RKE2Installer instance
        node: Node to install Cilium manifest on
    """
    try:
        # Get the absolute path to the rke2 module directory
        rke2_module_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        logger.debug(f"RKE2 module directory: {rke2_module_dir}")
        
        # Try multiple possible locations for the Cilium manifest
        possible_paths = [
            os.path.join(rke2_module_dir, 'templates', 'cilium.yaml'),
            os.path.join(os.path.dirname(rke2_module_dir), 'rke2', 'templates', 'cilium.yaml'),
            os.path.join(os.getcwd(), 'infractl', 'modules', 'rke2', 'templates', 'cilium.yaml')
        ]
        
        local_cilium_path = None
        for path in possible_paths:
            if os.path.exists(path):
                local_cilium_path = path
                break
                
        if not local_cilium_path:
            error_msg = f"Cilium manifest not found in any of these locations: {possible_paths}"
            logger.error(error_msg)
            raise FileNotFoundError(error_msg)
        
        remote_manifest_path = '/var/lib/rancher/rke2/server/manifests/cilium.yaml'
        
        # Check if the remote file exists and has the same content
        try:
            # Create a checksum of the local file
            with open(local_cilium_path, 'rb') as f:
                local_checksum = hashlib.md5(f.read()).hexdigest()
            
            # Get checksum of remote file if it exists
            remote_checksum = installer._ssh_exec(
                node,
                f'sudo md5sum {remote_manifest_path} 2>/dev/null | cut -d" " -f1 || true',
                check=False
            ).strip()
            
            if remote_checksum == local_checksum:
                logger.info(f'✅ Cilium manifest is already up to date on {node.name}')
                return
                
        except Exception as e:
            logger.debug(f"Could not verify remote checksum: {str(e)}")
        
        # If we get here, we need to update the manifest
        logger.info(f'Updating Cilium manifest on {node.name}...')
        remote_temp_path = '/tmp/cilium.yaml'
        
        # Upload the file
        installer._sftp_put(node, local_cilium_path, remote_temp_path)
        
        # Move to final location with proper permissions atomically
        installer._ssh_exec(
            node,
            f'sudo mkdir -p $(dirname {remote_manifest_path}) && '
            f'sudo mv {remote_temp_path} {remote_manifest_path} && '
            f'sudo chmod 644 {remote_manifest_path} && '
            f'sudo chown root:root {remote_manifest_path}',
            check=True
        )
        
        logger.info(f'✅ Successfully updated Cilium manifest on {node.name}')
        
    except Exception as e:
        logger.error(f'❌ Failed to install Cilium manifest on {node.name}: {str(e)}')
        raise

def start_service(installer, node: Node, is_server: bool = True, force_cleanup: bool = False) -> None:
    """Start and enable RKE2 service on a node.
    
    Args:
        installer: RKE2Installer instance
        node: Node to start RKE2 on
        is_server: Whether this is a server or agent node
        force_cleanup: If True, force cleanup of etcd and other persistent data
                      (use with caution as it will delete cluster state)
    """
    role = 'server' if is_server else 'agent'
    service_name = f'rke2-{role}.service'
    
    try:
        logger.info(f'🚀 Starting {service_name} on {node.name}...')
        
        # Only clean up processes and data if explicitly requested or if it's a fresh start
        if force_cleanup:
            logger.info(f'🧹 Force cleaning up existing RKE2 processes and data on {node.name}...')
        else:
            logger.info(f'🧹 Cleaning up existing RKE2 processes on {node.name}...')
        

        # Stop and disable any existing RKE2 services
        for svc in ['rke2-server', 'rke2-agent']:
            installer._ssh_exec(
                node,
                f'sudo systemctl stop {svc} 2>/dev/null || true',
                check=False
            )
            installer._ssh_exec(
                node,
                f'sudo systemctl disable {svc} 2>/dev/null || true',
                check=False
            )
        
        # Kill any remaining RKE2 processes
        installer._ssh_exec(
            node,
            'sudo pkill -9 -f "rke2 server" || true && '
            'sudo pkill -9 -f "rke2 agent" || true && '
            'sudo pkill -9 -f "/var/lib/rancher/rke2" || true',
            check=False
        )
        
        # Define cleanup directories
        cleanup_dirs = [
            # Always clean up these directories
            '/var/lib/kubelet',
            '/etc/rancher/node',
            '/var/lib/rancher/rke2/agent',
        ]
        
        # Only clean up etcd and server data if force_cleanup is True
        if force_cleanup:
            logger.warning('⚠️  Force cleanup requested - removing etcd and server data')
            cleanup_dirs.extend([
                '/var/lib/rancher/rke2',
                '/etc/rancher/rke2',
                '/var/lib/rancher/etcd',
                '/var/lib/etcd',
                '/var/lib/rancher/rke2/server/db',
                '/var/lib/rancher/rke2/data'
            ])
        else:
            logger.info('⚠️  Preserving etcd and server data (use force_cleanup=True to remove)')
        
        for dir_path in cleanup_dirs:
            try:
                installer._ssh_exec(
                    node,
                    f'sudo rm -rf {dir_path} 2>/dev/null || true',
                    check=False
                )
                logger.debug(f'Cleaned up directory: {dir_path}')
            except Exception as e:
                logger.warning(f'Failed to clean up {dir_path}: {e}')
        
        # Ensure config directory exists with correct permissions
        config_dir = '/etc/rancher/rke2'
        installer._ssh_exec(
            node,
            f'sudo mkdir -p {config_dir} && '
            f'sudo chown -R root:root {config_dir} && '
            f'sudo chmod 750 {config_dir}',
            check=True
        )
        
        # Generate and write the full configuration using our template
        config = _get_node_config(installer, node, is_server)
        write_node_config(installer, node, config)
        logger.info(f'✅ RKE2 configuration applied successfully to {node.name}')
        
      
        # Reload systemd to pick up the new environment file
        installer._ssh_exec(node, 'sudo systemctl daemon-reload', check=True)
        
        # Enable the service if not already enabled
        installer._ssh_exec(
            node,
            f'sudo systemctl enable {service_name} || true',
            check=False
        )
        
        # Start the service with environment variables if needed
        logger.info(f'🚀 Starting {service_name} on {node.name}...')
        
        # For agent nodes, ensure the token is passed via environment
        if not is_server:
            installer._ssh_exec(
                node,
                f'sudo systemctl set-environment RKE2_TOKEN=\'{installer.cluster_token}\''
            )
        
        # Start the service with detailed logging
        logger.info(f'🚀 Starting {service_name} on {node.name}...')
        
        try:
            # First, ensure the service is stopped
            installer._ssh_exec(
                node,
                f'sudo systemctl stop {service_name} || true',
                check=False
            )
            
            # For bootstrap node, first start with API server disabled
            is_bootstrap = is_server and installer.bootstrap_ip == node.ip
            
            if is_bootstrap:
                logger.info('🔄 Bootstrap node detected - starting RKE2...')
                installer._ssh_exec(
                    node,
                    f'sudo systemctl start {service_name}'
                )
            else:
                # For non-bootstrap nodes, start normally
                start_output = installer._ssh_exec(
                    node,
                    f'sudo systemctl start {service_name} && echo "Service started successfully" || echo "Service start failed"',
                    check=False
                )
                logger.debug(f'Service start output: {start_output}')
            
            # Check service status
            status = installer._ssh_exec(
                node,
                f'sudo systemctl is-active {service_name} || echo "inactive"',
                check=False
            ).strip()
            
            if 'active' not in status.lower():
                # If service didn't start, get detailed logs
                logs = installer._ssh_exec(
                    node,
                    f'sudo journalctl -u {service_name} -n 50 --no-pager 2>/dev/null || echo "No journal logs available"',
                    check=False
                )
                logger.error(f'Service {service_name} failed to start. Status: {status}\nLogs:\n{logs}')
                
                # Check for common issues
                if 'port is already in use' in logs.lower():
                    logger.error('⚠️  Detected port conflict. Another service might be using the same port.')
                if 'certificate' in logs.lower() and 'expired' in logs.lower():
                    logger.error('⚠️  Detected certificate issue. The cluster certificates might be expired or invalid.')
                
                raise RuntimeError(f'Failed to start {service_name}. Status: {status}')
                
            logger.info(f'✅ Successfully started {service_name} on {node.name}')
            
        except Exception as e:
            # Get detailed error information
            logger.error(f'❌ Failed to start {service_name} on {node.name}: {e}')
            
            # Get service status and logs
            try:
                status = installer._ssh_exec(
                    node, 
                    f'sudo systemctl status {service_name} --no-pager || true',
                    check=False
                )
                logger.error(f'Service status for {service_name} on {node.name}:\n{status}')
                
                logs = installer._ssh_exec(
                    node, 
                    f'sudo journalctl -u {service_name} -n 50 --no-pager || true',
                    check=False
                )
                logger.error(f'Service logs for {service_name} on {node.name}:\n{logs}')
                
                # Check for common issues
                if 'failed to create listener' in logs.lower():
                    logger.error('⚠️  Detected port conflict. Another service might be using the same port.')
                
                if 'certificate' in logs.lower() and 'expired' in logs.lower():
                    logger.error('⚠️  Detected certificate issue. The cluster certificates might be expired or invalid.')
                
            except Exception as log_err:
                logger.error(f'Failed to get service logs: {log_err}')
            
            raise
        
        # Wait for the service to become active
        max_attempts = 30
        for attempt in range(1, max_attempts + 1):
            status = installer._ssh_exec(
                node,
                f'systemctl is-active {service_name} 2>/dev/null || echo "inactive"',
                check=False
            ).strip()
            
            if status == 'active':
                logger.info(f'✅ {service_name} is active on {node.name}')
                return
                
            if attempt < max_attempts:
                time.sleep(2)
        
        # If we get here, the service didn't start in time
        raise RuntimeError(f'Timed out waiting for {service_name} to start')
        
    except Exception as e:
        # Get detailed error information
        logger.error(f'❌ Failed to start {service_name} on {node.name}: {e}')
        
        # Get service status and logs
        try:
            status = installer._ssh_exec(
                node, 
                f'sudo systemctl status {service_name} --no-pager || true',
                check=False
            )
            logger.error(f'Service status for {service_name} on {node.name}:\n{status}')
            
            logs = installer._ssh_exec(
                node, 
                f'sudo journalctl -u {service_name} -n 50 --no-pager || true',
                check=False
            )
            logger.error(f'Service logs for {service_name} on {node.name}:\n{logs}')
            
            # Check for common issues
            if 'failed to create listener' in logs.lower():
                logger.error('⚠️  Detected port conflict. Another service might be using the same port.')
            
            if 'certificate' in logs.lower() and 'expired' in logs.lower():
                logger.error('⚠️  Detected certificate issue. The cluster certificates might be expired or invalid.')
            
        except Exception as log_err:
            logger.error(f'Failed to get service logs: {log_err}')
        
        raise RuntimeError(f'Failed to start {service_name} on {node.name}: {e}')

def stop_service(installer, node: Node, is_server: bool = True, cleanup: bool = False) -> None:
    """Stop and disable RKE2 service on a node.
    
    Args:
        installer: RKE2Installer instance
        node: Node to stop RKE2 on
        is_server: Whether this is a server or agent node
        cleanup: If True, also clean up etcd and other persistent data
                (use with caution as it will delete cluster state)
    """
    role = 'server' if is_server else 'agent'
    service_name = f'rke2-{role}.service'
    
    try:
        logger.info(f'🛑 Stopping {service_name} on {node.name}...')
        
        # Stop the service
        installer._ssh_exec(
            node,
            f'sudo systemctl stop {service_name} || true',
            check=False
        )
        
        # Disable the service
        installer._ssh_exec(
            node,
            f'sudo systemctl disable {service_name} || true',
            check=False
        )
        
        logger.info(f'✅ Successfully stopped {service_name} on {node.name}')
        
    except Exception as e:
        logger.warning(f'⚠️  Failed to stop {service_name} on {node.name}: {e}')

def restart_service(installer, node: Node, is_server: bool = True) -> None:
    """Restart RKE2 service on a node.
    
    Args:
        installer: RKE2Installer instance
        node: Node to restart service on
        is_server: Whether this is a server or agent node
    """
    stop_service(installer, node, is_server)
    start_service(installer, node, is_server)
