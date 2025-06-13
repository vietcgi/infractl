"""RKE2 verification and health checks.

This module contains functions to verify RKE2 installation and cluster health.
"""

import logging
import time
from typing import Dict, Any, List, Optional

from ..models import Node

logger = logging.getLogger("rke2.installer.verification")

def verify_installation(installer, node: Node, is_server: bool = True) -> bool:
    """Verify RKE2 installation on a node.
    
    Args:
        installer: RKE2Installer instance
        node: Node to verify
        is_server: Whether this is a server or agent installation
        
    Returns:
        bool: True if verification succeeds, False otherwise
    """
    role = 'server' if is_server else 'agent'
    logger.info(f'🔍 Verifying RKE2 {role} installation on {node.name}')
    
    try:
        # Check if RKE2 binary exists in PATH
        rke2_bin = installer._ssh_exec(node, 'command -v rke2 || echo ""', check=False).strip()
        
        # If not in PATH, check standard locations
        if not rke2_bin:
            for path in ['/usr/local/bin/rke2', '/var/lib/rancher/rke2/bin/rke2']:
                exists = installer._ssh_exec(
                    node, 
                    f'[ -f {path} ] && echo "found" || echo ""', 
                    check=False
                ).strip()
                if exists == 'found':
                    logger.info(f'✅ Found RKE2 binary at {path} on {node.name}')
                    rke2_bin = path
                    break
            
            if not rke2_bin:
                logger.error('❌ RKE2 binary not found in PATH or standard locations')
                return False
        
        # Check version
        version = installer._ssh_exec(
            node, 
            f'{rke2_bin} --version || echo ""', 
            check=False
        ).strip()
        
        if version:
            logger.info(f'✅ RKE2 version: {version}')
        else:
            logger.warning('⚠️  Could not determine RKE2 version')
        
        # Check kubectl for server nodes
        if is_server:
            kubectl_bin = installer._ssh_exec(
                node, 
                'command -v kubectl || echo ""', 
                check=False
            ).strip()
            
            if not kubectl_bin:
                logger.warning('⚠️  kubectl not found in PATH')
                
                # Try to find kubectl in RKE2 bin directory
                rke2_bin_dir = '/var/lib/rancher/rke2/bin'
                kubectl_path = f'{rke2_bin_dir}/kubectl'
                
                exists = installer._ssh_exec(
                    node, 
                    f'[ -f {kubectl_path} ] && echo "found" || echo ""', 
                    check=False
                ).strip()
                
                if exists == 'found':
                    logger.info(f'✅ Found kubectl at {kubectl_path}')
                    
                    # Create symlink to /usr/local/bin
                    installer._ssh_exec(
                        node, 
                        f'sudo ln -sf {kubectl_path} /usr/local/bin/kubectl',
                        check=False
                    )
                else:
                    logger.warning('⚠️  kubectl not found in RKE2 bin directory')
        
        logger.info(f'✅ RKE2 {role} installation verified on {node.name}')
        return True
        
    except Exception as e:
        logger.error(f'❌ Verification failed on {node.name}: {e}')
        return False

def wait_for_ready(installer, node: Node, timeout: int = 600) -> bool:
    """Wait for RKE2 to be ready on a node.
    
    Args:
        installer: RKE2Installer instance
        node: Node to check
        timeout: Timeout in seconds
        
    Returns:
        bool: True if RKE2 is ready, False otherwise
    """
    logger.info(f'⏳ Waiting for RKE2 to be ready on {node.name} (timeout: {timeout}s)')
    
    start_time = time.time()
    last_error = ""
    check_count = 0
    
    # Fix kubeconfig permissions if needed
    installer._ssh_exec(
        node,
        "sudo chmod 644 /etc/rancher/rke2/rke2.yaml 2>/dev/null || true",
        check=False
    )
    
    # Ensure kubectl is in PATH
    installer._ssh_exec(
        node,
        "echo 'export PATH=$PATH:/var/lib/rancher/rke2/bin' | sudo tee -a /root/.bashrc",
        check=False
    )
    
    while time.time() - start_time < timeout:
        check_count += 1
        try:
            # Check if the service is running
            status = installer._ssh_exec(
                node, 
                "sudo systemctl is-active rke2-server 2>/dev/null || sudo systemctl is-active rke2-agent 2>/dev/null || echo 'inactive'",
                check=False
            ).strip().lower()
            
            if 'active' not in status:
                last_error = f"Service not active (status: {status})"
                if check_count % 12 == 0:  # Log every minute
                    logger.info(f"⏳ Waiting for RKE2 service to be active on {node.name}...")
                time.sleep(5)
                continue
            
            # Try to get kubectl version with proper permissions
            kubectl_cmd = (
                "sudo KUBECONFIG=/etc/rancher/rke2/rke2.yaml "
                "KUBECONFIG_MODE=644 "
                "/var/lib/rancher/rke2/bin/kubectl version --output=json"
            )
            
            version = installer._ssh_exec(node, kubectl_cmd, check=False)
            if 'serverVersion' in version:
                logger.info(f"✅ RKE2 is ready on {node.name}")
                
                # Copy kubeconfig to user's home directory with proper permissions
                installer._ssh_exec(
                    node,
                    "mkdir -p ~/.kube && "
                    "sudo cp /etc/rancher/rke2/rke2.yaml ~/.kube/config && "
                    "sudo chown $(id -u):$(id -g) ~/.kube/config && "
                    "chmod 600 ~/.kube/config"
                )
                
                return True
            
            last_error = f"Failed to get kubectl version: {version}"
            
            if check_count % 12 == 0:  # Log every minute
                logger.info(f"⏳ Waiting for RKE2 API to be ready on {node.name}...")
            
        except Exception as e:
            last_error = str(e)
            if check_count % 12 == 0:  # Log every minute
                logger.warning(f"⚠️  Error checking RKE2 status on {node.name}: {last_error}")
        
        time.sleep(5)
    
    # If we got here, we timed out
    try:
        # Get service logs for debugging
        logs = installer._ssh_exec(
            node,
            "sudo journalctl -u rke2-server -n 50 --no-pager 2>/dev/null || "
            "sudo journalctl -u rke2-agent -n 50 --no-pager 2>/dev/null || "
            "echo 'No service logs available'",
            check=False
        )
        logger.error(f"📜 RKE2 service logs from {node.name}:\n{logs}")
    except Exception as e:
        logger.error(f"Failed to get service logs from {node.name}: {e}")
    
    logger.error(f"❌ Timed out waiting for RKE2 to be ready on {node.name}. Last error: {last_error}")
    return False
