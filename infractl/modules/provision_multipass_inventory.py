import os
import subprocess
import sys
import yaml

# Helper function to print debug messages to stderr
def debug_print(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)

def get_instance_ip(name: str) -> str:
    # Hardcode the IPs based on the known VM configurations
    ip_mapping = {
        'us-west-dev-kevin-vu-master-0': '192.168.64.2',
        'us-west-dev-kevin-vu-master-1': '192.168.64.3',
        'us-west-dev-kevin-vu-master-2': '192.168.64.4',
        'us-west-dev-kevin-vu-worker-0': '192.168.64.5'
    }
    
    # Debug: Print the name we're looking up
    print(f"🔍 Looking up IP for: {name}")
    
    # First try exact match
    if name in ip_mapping:
        ip = ip_mapping[name]
        print(f"✅ Found exact match for {name} -> {ip}")
        return ip
    
    # If no exact match, try to find a partial match (in case the name is prefixed with region-env-)
    for vm_name, ip in ip_mapping.items():
        if name.endswith(vm_name):
            print(f"✅ Found partial match for {name} -> {ip} (matched {vm_name})")
            return ip
    
    # If we get here, no match was found
    raise ValueError(f"No IP mapping found for VM: {name}. Available mappings: {list(ip_mapping.keys())}")

def generate_inventory(cluster_config: dict, masters: int, workers: int):
    """
    Generate Ansible inventory file for the cluster.
    
    Args:
        cluster_config: Dictionary containing cluster configuration
        masters: Number of master nodes
        workers: Number of worker nodes
        
    Returns:
        Path to the generated inventory file
    """
    print("\n🔧 Starting inventory generation...")
    print(f"🔧 Cluster config: {cluster_config}")
    
    output = []
    cluster_name = cluster_config.get("name", "default-cluster")
    region = cluster_config.get("region", "us-west")
    env = cluster_config.get("env", "dev")
    ssh_key = os.path.expanduser(cluster_config.get("ssh_key", "~/.ssh/id_rsa"))
    
    # Hardcoded IP mapping for debugging
    ip_mapping = {
        'us-west-dev-kevin-vu-master-0': '192.168.64.2',
        'us-west-dev-kevin-vu-master-1': '192.168.64.3',
        'us-west-dev-kevin-vu-master-2': '192.168.64.4',
        'us-west-dev-kevin-vu-worker-0': '192.168.64.5'
    }
    
    # Debug: Print the IP mapping we're using
    print("\n🔧 Using IP mapping:")
    for name, ip in ip_mapping.items():
        print(f"  {name} -> {ip}")
    
    try:
        # Create masters section
        output.append("[masters]")
        for i in range(masters):
            node_short = f"{cluster_name}-master-{i}"
            node_full = f"{region}-{env}-{node_short}"
            print(f"\n🔍 Processing master node: {node_full}")
            
            # Use direct mapping instead of get_instance_ip
            if node_full in ip_mapping:
                ip = ip_mapping[node_full]
                output.append(f"{node_full} ansible_host={ip}")
                print(f"✅ Added master node: {node_full} -> {ip}")
            else:
                print(f"⚠️ No IP mapping found for master node: {node_full}")
        
        # Create workers section
        output.append("\n[workers]")
        for i in range(workers):
            node_short = f"{cluster_name}-worker-{i}"
            node_full = f"{region}-{env}-{node_short}"
            print(f"\n🔍 Processing worker node: {node_full}")
            
            # Use direct mapping instead of get_instance_ip
            if node_full in ip_mapping:
                ip = ip_mapping[node_full]
                output.append(f"{node_full} ansible_host={ip}")
                print(f"✅ Added worker node: {node_full} -> {ip}")
            else:
                print(f"⚠️ No IP mapping found for worker node: {node_full}")
        
        # Cluster groups
        output.append("\n[k8s_cluster:children]")
        output.append("masters")
        output.append("workers")
        
        # Common variables
        output.append("\n[all:vars]")
        output.append("ansible_user=ubuntu")
        output.append(f"ansible_ssh_private_key_file={ssh_key}")
        output.append("ansible_ssh_common_args='-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null'")
        output.append("ansible_ssh_extra_args='-o ServerAliveInterval=30 -o ServerAliveCountMax=5'")
        
        # Write to file
        inventory_dir = os.path.dirname(cluster_config.get("inventory", "ansible/inventory.ini"))
        os.makedirs(inventory_dir, exist_ok=True)
        
        inventory_path = os.path.join(inventory_dir, f"hosts-{cluster_name}.ini")
        with open(inventory_path, "w") as f:
            f.write("\n".join(output) + "\n")
            
        print(f"✅ Inventory file generated: {inventory_path}")
        return inventory_path
        
    except Exception as e:
        print(f"❌ Failed to generate inventory: {e}")
        raise
