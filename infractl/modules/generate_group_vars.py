"""
Generate group_vars for RKE2 cluster configuration.
This module generates basic RKE2 configuration and lets Ansible handle HA mode logic.
"""
import os
import yaml
import ipaddress
from pathlib import Path
from typing import List, Dict, Any

def generate_consistent_token(cluster_name: str, length: int = 32) -> str:
    """Generate a consistent token based on the cluster name."""
    import hashlib
    # Create a hash of the cluster name to ensure consistency
    hash_obj = hashlib.sha256(cluster_name.encode())
    # Use first 'length' characters of the hex digest
    return hash_obj.hexdigest()[:length]

# Constants
# Default version will be overridden by cluster config
DEFAULT_K8S_VERSION = "v1.33.1+rke2r1"
# Token will be generated consistently based on cluster name
DEFAULT_API_PORT = 6443
DEFAULT_HA_API_PORT = 9345

def is_valid_ip(ip: str) -> bool:
    """Check if a string is a valid IP address."""
    try:
        ipaddress.ip_address(ip)
        return True
    except ValueError:
        return False

def resolve_master_ips(inventory_path: str, group_name: str = "masters") -> List[str]:
    """
    Parse an Ansible inventory file to extract master node IPs.
    
    Args:
        inventory_path: Path to the Ansible inventory file
        group_name: Name of the group containing master nodes
        
    Returns:
        List of IP addresses
    """
    print(f"🔍 Parsing inventory for master IPs: {inventory_path}")
    
    if not Path(inventory_path).exists():
        raise FileNotFoundError(f"Inventory file not found: {inventory_path}")

    master_ips = []
    
    try:
        with open(inventory_path, 'r') as f:
            content = f.read()
            
        # Find the masters group
        group_section = f"[{group_name}]"
        if group_section not in content:
            print(f"⚠️  Warning: No [{group_name}] group found in inventory")
            return []
            
        # Extract hostnames from the group
        group_content = content.split(group_section)[1].split("[")[0]
        for line in group_content.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                hostname = line.split()[0]
                if "ansible_host=" in line:
                    ip = line.split("ansible_host=")[1].split()[0]
                    if is_valid_ip(ip):
                        master_ips.append(ip)
                        print(f"✅ Found master IP: {ip}")
                    else:
                        print(f"⚠️  Invalid IP format for {hostname}: {ip}")
                else:
                    print(f"⚠️  No ansible_host found for {hostname}")
                    
    except Exception as e:
        print(f"❌ Error parsing inventory: {e}")
        raise
        
    return master_ips

def generate_group_vars(cluster_config: Dict[str, Any], inventory_path: str, output_path: str) -> Dict[str, Any]:
    """
    Generate group_vars for RKE2 cluster configuration.
    
    Args:
        cluster_config: Dictionary containing cluster configuration
        inventory_path: Path to the Ansible inventory file
        output_path: Path to save the generated group_vars file
        
    Returns:
        Dictionary containing the generated group_vars
    """
    if not cluster_config:
        raise ValueError("cluster_config cannot be empty")
    
    print(f"🔍 Cluster config: {cluster_config}")
    print(f"🔍 Inventory path: {inventory_path}")
    print(f"🔍 Output path: {output_path}")
    
    # Get master IPs from inventory
    master_ips = []
    raw_ips = resolve_master_ips(inventory_path)
    
    # Deduplicate IPs while preserving order
    seen = set()
    for ip in raw_ips:
        if ip not in seen:
            seen.add(ip)
            master_ips.append(ip)
    
    print(f"🔍 Unique master IPs: {master_ips}")
    
    # Generate a consistent token based on cluster name
    cluster_name = cluster_config.get("name", "default-cluster")
    # Always generate a consistent token based on cluster name
    default_token = generate_consistent_token(cluster_name)
    
    # Determine if this is an HA cluster (explicitly set in config or more than 1 master)
    is_ha = bool(cluster_config.get('ha', False) or len(master_ips) > 1)
    
    # Common configuration for all clusters
    data = {
        "rke2_version": cluster_config.get("kubernetes_version", DEFAULT_K8S_VERSION),
        "rke2_token": cluster_config.get("token", default_token),
        "rke2_tls_san": master_ips,
        "rke2_download_kubeconf": True,
        "rke2_cni": ["cilium"],
        "rke2_custom_manifests": ["cilium.yaml"],
        "rke2_disable": [
            'rke2-cilium',
            'rke2-canal',
            'rke2-coredns',
            'rke2-ingress-nginx',
            'rke2-metrics-server'
        ]
    }
    
    # Add HA-specific configurations if this is an HA cluster
    if is_ha:
        data.update({
            "rke2_ha_mode": True,
            "rke2_api_ip": cluster_config.get('ha_api_ip', master_ips[0] if master_ips else None),
            "rke2_ha_mode_kubevip": True,
            "rke2_kubevip_cloud_provider_enable": True,
            "rke2_kubevip_svc_enable": True,
            "rke2_kubevip_ipvs_lb_enable": True
        })
    
    # Set default servers, will be overridden by Ansible if needed
    if is_ha:
        data["rke2_servers"] = [f"https://{cluster_config.get('ha_api_ip', master_ips[0] if master_ips else '0.0.0.0')}:{DEFAULT_API_PORT}"]
    
    # Ensure output directory exists
    output_dir = os.path.dirname(output_path)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir, exist_ok=True)
        print(f"📁 Created directory: {output_dir}")
    
    # Write the configuration
    try:
        with open(output_path, 'w') as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)
        print(f"✅ Successfully generated group_vars at {output_path}")
    except IOError as e:
        print(f"❌ Failed to write group_vars: {e}")
        raise
    
    return data
