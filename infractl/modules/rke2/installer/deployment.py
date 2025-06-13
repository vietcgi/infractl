"""RKE2 cluster deployment orchestration.

This module handles the deployment of RKE2 clusters across multiple nodes.
"""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Any, Optional, Tuple

from ..models import Node, DeploymentState
from . import configuration, service, verification

logger = logging.getLogger("rke2.installer.deployment")

def deploy_node(installer, node: Node, master_nodes: List[Node] = None) -> Tuple[bool, str]:
    """Deploy RKE2 on a single node.
    
    Args:
        installer: RKE2Installer instance
        node: Node to deploy on
        master_nodes: List of master nodes (required for worker nodes)
        
    Returns:
        tuple: (success: bool, message: str)
    """
    try:
        logger.info(f"🚀 Starting RKE2 deployment on {node.name} ({node.ip})")
        
        # Set bootstrap IP if this is the first master
        is_server = node.role == 'master'
        if is_server and not installer.bootstrap_ip:
            installer.bootstrap_ip = node.ip
            logger.info(f"🔧 Set bootstrap IP to: {installer.bootstrap_ip}")
        
        # Install RKE2
        service.install_rke2(installer, node, is_server)
        
        # Generate and write node configuration
        config = configuration.generate_node_config(node, installer.cluster_token, master_nodes)
        configuration.write_node_config(installer, node, config)
        
        # Start the appropriate service
        service.start_service(installer, node, is_server)
        
        # For the first master, wait for it to be ready and get the node token
        if node.role == 'master' and installer.bootstrap_ip == node.ip:
            if not verification.wait_for_ready(installer, node):
                return False, f"First master {node.name} did not become ready"
            
            # Get the node token for other nodes to join
            installer._get_node_token(node)
        
        # Verify installation
        if not verification.verify_installation(installer, node, is_server):
            return False, f"Verification failed for {node.name}"
        
        return True, f"Successfully deployed RKE2 on {node.name}"
        
    except Exception as e:
        error_msg = f"Failed to deploy RKE2 on {node.name}: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return False, error_msg

def deploy_cluster(installer, master_nodes: List[Node], worker_nodes: List[Node] = None) -> Dict[str, Any]:
    """Deploy an RKE2 cluster.
    
    Args:
        installer: RKE2Installer instance
        master_nodes: List of master nodes
        worker_nodes: Optional list of worker nodes
        
    Returns:
        dict: Deployment results and status
    """
    if not master_nodes:
        raise ValueError("At least one master node is required")
    
    worker_nodes = worker_nodes or []
    all_nodes = master_nodes + worker_nodes
    
    # Set up deployment state
    installer.state = DeploymentState()
    installer.state.total_batches = 2  # Masters first, then workers
    results = {
        'success': False,
        'masters': {},
        'workers': {},
        'errors': []
    }
    
    try:
        # Deploy master nodes
        installer.state.update_phase('deploying_masters')
        installer.state.current_batch = 1
        
        with ThreadPoolExecutor(max_workers=min(10, len(master_nodes))) as executor:
            future_to_node = {
                executor.submit(deploy_node, installer, node, master_nodes): node
                for node in master_nodes
            }
            
            for future in as_completed(future_to_node):
                node = future_to_node[future]
                try:
                    success, message = future.result()
                    results['masters'][node.name] = {
                        'success': success,
                        'message': message
                    }
                    if not success:
                        results['errors'].append(f"Failed to deploy master {node.name}: {message}")
                except Exception as e:
                    error_msg = f"Error processing master {node.name}: {str(e)}"
                    logger.error(error_msg, exc_info=True)
                    results['errors'].append(error_msg)
        
        # Verify at least one master is up
        master_up = any(
            result.get('success', False)
            for result in results['masters'].values()
        )
        
        if not master_up:
            results['errors'].append("No master nodes were successfully deployed")
            return results
        
        # Deploy worker nodes
        if worker_nodes:
            installer.state.update_phase('deploying_workers')
            installer.state.current_batch = 2
            
            with ThreadPoolExecutor(max_workers=min(20, len(worker_nodes))) as executor:
                future_to_node = {
                    executor.submit(deploy_node, installer, worker, master_nodes): worker
                    for worker in worker_nodes
                }
                
                for future in as_completed(future_to_node):
                    worker = future_to_node[future]
                    try:
                        success, message = future.result()
                        results['workers'][worker.name] = {
                            'success': success,
                            'message': message
                        }
                        if not success:
                            results['errors'].append(f"Failed to deploy worker {worker.name}: {message}")
                    except Exception as e:
                        error_msg = f"Error processing worker {worker.name}: {str(e)}"
                        logger.error(error_msg, exc_info=True)
                        results['errors'].append(error_msg)
        
        # Check cluster health
        first_master = master_nodes[0]
        health = check_cluster_health(installer, first_master)
        results['health'] = health
        
        if not health.get('healthy', False):
            results['errors'].append("Cluster health check failed")
        
        results['success'] = len(results['errors']) == 0
        return results
        
    except Exception as e:
        error_msg = f"Cluster deployment failed: {str(e)}"
        logger.error(error_msg, exc_info=True)
        results['errors'].append(error_msg)
        return results
    finally:
        installer.state.update_phase('completed')
        installer.connection_pool.close_all()

def check_cluster_health(installer, master_node: Node) -> Dict[str, Any]:
    """Check the health of the RKE2 cluster.
    
    Args:
        installer: RKE2Installer instance
        master_node: A master node to run health checks from
        
    Returns:
        dict: Health check results
    """
    result = {
        'healthy': False,
        'nodes': {},
        'components': {},
        'errors': []
    }
    
    try:
        # Check if kubectl is working and can list nodes
        nodes_cmd = "export KUBECONFIG=/etc/rancher/rke2/rke2.yaml && /var/lib/rancher/rke2/bin/kubectl get nodes -o json"
        nodes_json = installer._ssh_exec(master_node, nodes_cmd)
        
        # Parse nodes
        import json
        nodes = json.loads(nodes_json)
        
        if 'items' not in nodes:
            result['errors'].append("Failed to get nodes from cluster")
            return result
            
        # Check node statuses
        for node in nodes['items']:
            node_name = node['metadata']['name']
            node_info = {
                'name': node_name,
                'ready': False,
                'statuses': {}
            }
            
            # Check if node is ready
            for condition in node.get('status', {}).get('conditions', []):
                cond_type = condition['type']
                cond_status = condition['status'] == 'True'
                node_info['statuses'][cond_type] = cond_status
                
                if cond_type == 'Ready':
                    node_info['ready'] = cond_status
            
            result['nodes'][node_name] = node_info
            
            if not node_info['ready']:
                result['errors'].append(f"Node {node_name} is not ready")
        
        # Check core components
        components_cmd = (
            "export KUBECONFIG=/etc/rancher/rke2/rke2.yaml && "
            "/var/lib/rancher/rke2/bin/kubectl get pods -A -l app.kubernetes.io/name in (kube-apiserver,kube-controller-manager,kube-scheduler,etcd,helm-install) "
            "-o json"
        )
        
        try:
            components_json = installer._ssh_exec(master_node, components_cmd)
            components = json.loads(components_json)
            
            for pod in components.get('items', []):
                pod_name = pod['metadata']['name']
                namespace = pod['metadata']['namespace']
                status = pod['status']['phase']
                
                component_info = {
                    'name': pod_name,
                    'namespace': namespace,
                    'status': status,
                    'ready': status == 'Running'
                }
                
                result['components'][f"{namespace}/{pod_name}"] = component_info
                
                if status != 'Running':
                    result['errors'].append(f"Pod {namespace}/{pod_name} is not running (status: {status})")
                    
        except Exception as e:
            error_msg = f"Failed to check core components: {str(e)}"
            logger.error(error_msg, exc_info=True)
            result['errors'].append(error_msg)
        
        # Overall health status
        result['healthy'] = len(result['errors']) == 0
        
    except Exception as e:
        error_msg = f"Cluster health check failed: {str(e)}"
        logger.error(error_msg, exc_info=True)
        result['errors'].append(error_msg)
    
    return result
