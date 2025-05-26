import subprocess
import yaml

def get_instance_ip(name: str) -> str:
    try:
        print(f"🔁 Checking IP for Multipass VM → {name}")
        result = subprocess.run(["multipass", "info", name, "--format", "yaml"], capture_output=True, text=True)
        print(f"[DEBUG] Return code: {result.returncode}")
        print(f"[DEBUG] STDOUT for {name}:
{result.stdout}")
        data = yaml.safe_load(result.stdout)
        ip = data.get(name, [{}])[0].get("ipv4", ["0.0.0.0"])[0]
        print(f"✅ IP for {name}: {ip}")
        return ip
    except Exception as e:
        print(f"⚠️ Exception while getting IP for {name}: {e}")
    return "0.0.0.0"

def generate_inventory(name: str, masters: int, workers: int):
    output = []

    output.append("[masters]")
    for i in range(masters):
        node = f"{name}-master"
        ip = get_instance_ip(node)
        output.append(f"{node} ansible_host={ip} ansible_user=ubuntu ansible_private_key_file=~/.ssh/id_rsa")

    output.append("\n[workers]")
    for i in range(workers):
        node = f"{name}-worker"
        ip = get_instance_ip(node)
        output.append(f"{node} ansible_host={ip} ansible_user=ubuntu ansible_private_key_file=~/.ssh/id_rsa")

    output.append("\n[k8s_cluster:children]")
    output.append("masters")
    output.append("workers")

    path = f"ansible/hosts-{name}.ini"
    with open(path, "w") as f:
        f.write("\n".join(output) + "\n")

    print(f"📄 Inventory updated: {path}")
