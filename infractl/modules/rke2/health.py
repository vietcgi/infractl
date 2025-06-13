"""RKE2 cluster health checks and monitoring."""
import time
import logging
from typing import Dict, Any
from .models import Node

logger = logging.getLogger("rke2.health")

def wait_for_control_plane_ready(installer, master_node: Node, timeout: int = 300) -> bool:
    """Wait for the control plane to be ready.
    
    Args:
        installer: RKE2Installer instance
        master_node: The master node to check
        timeout: Timeout in seconds
        
    Returns:
        bool: True if control plane is ready, False otherwise
    """
    logger.info("Waiting for control plane to be ready on %s...", master_node.name)
    start_time = time.time()

    while time.time() - start_time < timeout:
        try:
            # Check if kubelet is running
            status = installer.ssh_exec(
                master_node, 
                "systemctl is-active rke2-server", 
                check=False
            )
            
            if "active" not in status.lower():
                time.sleep(5)
                continue

            # Check if API server is responding
            kubeconfig = "/etc/rancher/rke2/rke2.yaml"
            cmd = f"kubectl --kubeconfig={kubeconfig} get nodes --request-timeout=5s"
            result = installer.ssh_exec(master_node, cmd, check=False)

            if "Ready" in result:
                logger.info("Control plane is ready")
                return True

        except Exception as e:
            logger.debug("Control plane not ready yet: %s", str(e))

        time.sleep(5)

    logger.error("Timed out waiting for control plane to be ready")
    return False

def check_cluster_health(installer, master_node: Node) -> Dict[str, Any]:
    """Check the health of the cluster.
    
    Args:
        installer: RKE2Installer instance
        master_node: The master node to run health checks from
        
    Returns:
        Dict containing health status and details
    """
    health = {
        'healthy': False,
        'nodes': {},
        'pods': {},
        'issues': []
    }

    try:
        kubeconfig = "/etc/rancher/rke2/rke2.yaml"

        # Check node status
        cmd = f"kubectl --kubeconfig={kubeconfig} get nodes -o wide"
        nodes_output = installer.ssh_exec(master_node, cmd)
        health['nodes']['output'] = nodes_output

        # Check for NotReady nodes
        if "NotReady" in nodes_output:
            health['issues'].append("Some nodes are not in Ready state")

        # Check pod status
        cmd = (
            f"kubectl --kubeconfig={kubeconfig} "
            "get pods -A -o wide --field-selector=status.phase!=Running"
        )
        not_running_pods = installer.ssh_exec(master_node, cmd)

        if "No resources found" not in not_running_pods:
            health['issues'].append("Some pods are not in Running state")
            health['pods']['not_running'] = not_running_pods

        # Check core components
        cmd = (
            f"kubectl --kubeconfig={kubeconfig} "
            "get pods -n kube-system -l app.kubernetes.io/name!=helm -o wide"
        )
        system_pods = installer.ssh_exec(master_node, cmd)
        health['pods']['system'] = system_pods

        # If we got this far and no issues were found, cluster is healthy
        if not health['issues']:
            health['healthy'] = True

    except Exception as e:
        health['issues'].append(f"Health check failed: {str(e)}")

    return health
