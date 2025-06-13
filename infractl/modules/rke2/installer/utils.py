"""Utility functions for the RKE2 installer."""

import logging
import os
import random
import string
from typing import Any, Dict, List, Optional, Tuple

import yaml

logger = logging.getLogger("rke2.installer.utils")


def generate_token(length: int = 32) -> str:
    """Generate a random token for cluster authentication.
    
    Args:
        length: Length of the token to generate
        
    Returns:
        str: A random token string
    """
    chars = string.ascii_letters + string.digits
    return ''.join(random.choice(chars) for _ in range(length))


def write_yaml_file(path: str, data: Dict[str, Any], mode: int = 0o600) -> None:
    """Write a YAML file with the given data.
    
    Args:
        path: Path to the YAML file
        data: Data to write as YAML
        mode: File permissions (default: 0o600)
        
    Raises:
        IOError: If the file cannot be written
    """
    try:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False)
        os.chmod(path, mode)
    except (IOError, OSError) as e:
        logger.error(f"Failed to write YAML file {path}: {e}")
        raise


def read_yaml_file(path: str) -> Dict[str, Any]:
    """Read a YAML file and return its contents as a dictionary.
    
    Args:
        path: Path to the YAML file
        
    Returns:
        dict: The parsed YAML data
        
    Raises:
        FileNotFoundError: If the file does not exist
        yaml.YAMLError: If the file is not valid YAML
    """
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        logger.error(f"YAML file not found: {path}")
        raise
    except yaml.YAMLError as e:
        logger.error(f"Invalid YAML in {path}: {e}")
        raise


def merge_dicts(base: Dict[Any, Any], override: Dict[Any, Any]) -> Dict[Any, Any]:
    """Recursively merge two dictionaries.
    
    Args:
        base: Base dictionary
        override: Dictionary with values to override
        
    Returns:
        dict: Merged dictionary
    """
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = merge_dicts(result[key], value)
        else:
            result[key] = value
    return result


def parse_kubectl_output(output: str) -> List[Dict[str, Any]]:
    """Parse kubectl output into a list of dictionaries.
    
    Args:
        output: Raw kubectl output
        
    Returns:
        list: List of parsed resources
    """
    try:
        return yaml.safe_load(output)['items']
    except (yaml.YAMLError, KeyError, TypeError):
        return []


def validate_node(node: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Validate a node configuration dictionary.
    
    Args:
        node: Node configuration to validate
        
    Returns:
        tuple: (is_valid, error_messages)
    """
    errors = []
    
    if not node.get('name'):
        errors.append("Node name is required")
    if not node.get('ip'):
        errors.append("Node IP is required")
    if not node.get('role') or node['role'] not in ['master', 'worker']:
        errors.append("Node role must be either 'master' or 'worker'")
    
    return len(errors) == 0, errors


def get_public_ip() -> str:
    """Get the public IP address of the current machine.
    
    Returns:
        str: Public IP address or '127.0.0.1' if detection fails
    """
    import socket
    try:
        # Create a socket connection to a public DNS server
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception as e:
        logger.warning(f"Failed to detect public IP: {e}")
        return '127.0.0.1'
