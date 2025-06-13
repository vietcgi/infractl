# infractl/modules/provision_multipass.py
import os
import subprocess
import time
import json
import yaml
from pathlib import Path

def provision(config: dict, refresh_only: bool = False):
    name = config["name"]
    os_version = config.get("os", "ubuntu@24.04")
    nodes = config.get("masters", []) + config.get("agents", [])

    ips = {}
    for node in nodes:
        vm_name = node["name"]
        print(f"🔁 Checking IP for Multipass VM → {vm_name}")
        try:
            result = subprocess.run([
                "multipass", "info", vm_name, "--format", "json"
            ], capture_output=True, text=True, check=True)
            data = json.loads(result.stdout)
            # Get all IPs and filter out the VIP (192.168.64.100)
            all_ips = data["info"][vm_name].get("ipv4", [])
            if not all_ips:
                print(f"⚠️  No IPs found for {vm_name}")
                continue
                
            # Convert to list if it's a string
            ip_list = [all_ips] if isinstance(all_ips, str) else all_ips
            
            # Filter out the VIP and empty strings
            valid_ips = [ip for ip in ip_list if ip and ip != '192.168.64.100']
            
            if not valid_ips:
                print(f"⚠️  No valid IPs found for {vm_name} (after filtering)")
                continue
                
            # Use the first valid IP and store it with the node name as the key
            ips[vm_name] = valid_ips[0]
            print(f"✅ Assigned IP {ips[vm_name]} to {vm_name}")
        except Exception:
            print(f"ℹ️  VM {vm_name} not found. Launching new instance...")
            if not refresh_only:
                subprocess.run([
                    "multipass", "launch", os_version,
                    "--name", vm_name,
                    "--cpus", "2",
                    "--memory", "6G",
                    "--disk", "30G"
                ], check=True)
                print(f"✅ Launched: {vm_name}")
                time.sleep(5)
                result = subprocess.run([
                    "multipass", "info", vm_name, "--format", "json"
                ], capture_output=True, text=True, check=True)
                data = json.loads(result.stdout)
                # Get all IPs and filter out the VIP (192.168.64.100)
                all_ips = data["info"][vm_name].get("ipv4", [])
                if not all_ips:
                    print(f"⚠️  No IPs found for {vm_name} after launch")
                    continue
                    
                # Convert to list if it's a string
                ip_list = [all_ips] if isinstance(all_ips, str) else all_ips
                
                # Filter out the VIP and empty strings
                valid_ips = [ip for ip in ip_list if ip and ip != '192.168.64.100']
                
                if not valid_ips:
                    print(f"⚠️  No valid IPs found for {vm_name} (after filtering)")
                    continue
                    
                # Use the first valid IP and store it with the node name as the key
                ips[vm_name] = valid_ips[0]
                print(f"✅ Assigned IP {ips[vm_name]} to {vm_name} after launch")

            # Inject SSH key
            print(f"🔐 Adding ~/.ssh/id_rsa.pub to authorized_keys on {vm_name}...")
            try:
                with open(Path.home() / ".ssh/id_rsa.pub", "r") as keyfile:
                    pubkey = keyfile.read().strip()
                    subprocess.run([
                        "multipass", "exec", vm_name, "--", "bash", "-c",
                        f"mkdir -p /home/ubuntu/.ssh && echo '{pubkey}' >> /home/ubuntu/.ssh/authorized_keys && "
                        "chown -R ubuntu:ubuntu /home/ubuntu/.ssh && chmod 600 /home/ubuntu/.ssh/authorized_keys && "
                        "sudo apt-get install -y python3 python3-pip curl && sudo ln -sf /usr/bin/python3 /usr/bin/python"
                    ], check=True)
                    print(f"✅ Public key injected into {vm_name}")
            except Exception as e:
                print(f"❌ Failed to inject SSH key into {vm_name}: {e}")

    # Write inventory
    inventory = config["inventory"]
    inventory_lines = [
        "[masters]",
        *[
            f"{node['name']} ansible_host={ips.get(node['name'], '0.0.0.0')}"
            for node in config["masters"]
        ],
        "\n[workers]",
        *[
            f"{node['name']} ansible_host={ips.get(node['name'], '0.0.0.0')}"
            for node in config["agents"]
        ],
        "\n[k8s_cluster:children]",
        "masters",
        "workers",
        "\n[all:vars]",
        "ansible_user=ubuntu",
        f"ansible_ssh_private_key_file={os.path.expanduser(config.get('ssh_key', '~/.ssh/id_rsa'))}",
        "ansible_ssh_common_args='-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null'"
    ]

    # Ensure inventory directory exists
    os.makedirs(os.path.dirname(inventory), exist_ok=True)

    # Debug: Print the inventory content before writing
    print("\n🔧 Generated inventory content:")
    print("\n".join(inventory_lines))

    with open(inventory, "w") as f:
        f.write("\n".join(inventory_lines) + "\n")
    
    print(f"📄 Inventory updated: {inventory}")
    return ips
