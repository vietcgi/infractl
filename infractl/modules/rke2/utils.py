"""Utility functions for RKE2 installation and management."""
import yaml
import logging
import json
from typing import Dict, List, Any, Optional, Union
from pathlib import Path
from .models import Node

logger = logging.getLogger("rke2.utils")

def generate_node_config(node: Node, cluster_token: str, master_nodes: List[Node] = None) -> Dict[str, Any]:
    """Generate RKE2 configuration for a node.
    
    Args:
        node: The node to generate config for
        cluster_token: Shared token for cluster authentication
        master_nodes: List of master nodes in the cluster
        
    Returns:
        dict: RKE2 configuration dictionary
    """
    config: Dict[str, Any] = {
        'token': cluster_token,
        'node-ip': node.ip,
        'node-name': node.name,
        'kubelet-arg': [
            'max-pods=250',
            'image-gc-high-threshold=85',
            'image-gc-low-threshold=80'
        ]
    }

    if node.role == 'master':
        config['node-taint'] = [f"node-role.kubernetes.io/control-plane:NoSchedule"]
        if master_nodes and len(master_nodes) > 1:
            # For HA setup
            server_urls = [f"https://{n.ip}:9345" for n in master_nodes if n.name != node.name]
            config['server'] = f"https://{master_nodes[0].ip}:9345"
            config['cluster-init'] = True
    else:
        if not master_nodes:
            raise ValueError("Master nodes list is required for worker node configuration")
        config['server'] = f"https://{master_nodes[0].ip}:9345"

    # Add node labels if any
    if node.labels:
        config['node-label'] = [f"{k}={v}" for k, v in node.labels.items()]
    
    # Add node taints if any
    if node.taints:
        config['node-taint'] = config.get('node-taint', []) + node.taints
    
    return config

def write_config_file(config: Dict[str, Any], path: str) -> None:
    """Write configuration to a file in YAML format.
    
    Args:
        config: Configuration dictionary
        path: Path to write the config file to
    """
    try:
        config_dir = Path(path).parent
        config_dir.mkdir(parents=True, exist_ok=True)
        
        with open(path, 'w') as f:
            yaml.safe_dump(config, f, default_flow_style=False)
        logger.debug(f"Wrote config to {path}")
    except Exception as e:
        logger.error(f"Failed to write config to {path}: {str(e)}")
        raise

def parse_kubectl_output(output: str) -> List[Dict[str, str]]:
    """Parse kubectl output into a list of dictionaries.
    
    Args:
        output: Raw kubectl command output
        
    Returns:
        List of dictionaries representing the parsed output
    """
    if not output.strip():
        return []
        
    lines = output.strip().split('\n')
    if not lines:
        return []
        
    # Parse header
    headers = [h.strip() for h in lines[0].split()]
    result = []
    
    # Parse data rows
    for line in lines[1:]:
        if not line.strip():
            continue
            
        # Split on whitespace, but handle quoted strings properly
        parts = []
        current = ""
        in_quotes = False
        
        for char in line.strip():
            if char == '"':
                in_quotes = not in_quotes
            elif char.isspace() and not in_quotes:
                if current:
                    parts.append(current)
                    current = ""
                continue
            else:
                current += char
        
        if current:
            parts.append(current)
            
        if len(parts) >= len(headers):
            result.append(dict(zip(headers, parts)))
    
    return result

def validate_node(node: Node) -> bool:
    """Validate node configuration.
    
    Args:
        node: Node to validate
        
    Returns:
        bool: True if node is valid, False otherwise
    """
    if not node.name or not isinstance(node.name, str):
        logger.error(f"Node has invalid name: {node.name}")
        return False
        
    if not node.ip or not isinstance(node.ip, str):
        logger.error(f"Node {node.name} has invalid IP: {node.ip}")
        return False
        
    if node.role not in ['master', 'worker']:
        logger.error(f"Node {node.name} has invalid role: {node.role}")
        return False
        
    return True
