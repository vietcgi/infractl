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
        role = "master" if "master" in vm_name else "worker"
        print(f"🔁 Checking IP for Multipass VM → {vm_name}")
        try:
            result = subprocess.run([
                "multipass", "info", vm_name, "--format", "json"
            ], capture_output=True, text=True, check=True)
            data = json.loads(result.stdout)
            ips[role] = data["info"][vm_name]["ipv4"][0]
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
                ips[role] = data["info"][vm_name]["ipv4"][0]

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
            f"{node['name']} ansible_host={ips.get('master', '0.0.0.0')}"
            for node in config["masters"]
        ],
        "",
        "[workers]",
        *[
            f"{node['name']} ansible_host={ips.get('worker', '0.0.0.0')}"
            for node in config["agents"]
        ],
        "",
        "[k8s_cluster:children]",
        "masters",
        "workers",
        "",
        "[all:vars]",
        "ansible_user=ubuntu",
        "ansible_ssh_private_key_file=~/.ssh/id_rsa"
    ]
    Path("ansible").mkdir(parents=True, exist_ok=True)
    with open(inventory, "w") as f:
        f.write("\n".join(inventory_lines))
    print(f"📄 Inventory updated: {inventory}")
