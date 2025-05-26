import yaml

def resolve_master_ips(inventory_path: str, group_name: str = "masters") -> list[str]:
    print(f"🔍 Parsing inventory for master IPs: {inventory_path}")
    ips = []
    masters = []
    with open(inventory_path, "r") as f:
        group_found = False
        for line in f:
            line = line.strip()
            if line.startswith(f"[{group_name}]"):
                group_found = True
                continue
            if group_found:
                if line.startswith("[") or not line:
                    break
                masters.append(line.split()[0])
    print(f"🔍 Found masters: {masters}")

    with open(inventory_path, "r") as f:
        all_lines = f.readlines()

    for master in masters:
        for line in all_lines:
            if line.strip().startswith(master) and "ansible_host=" in line:
                parts = line.strip().split()
                for part in parts:
                    if part.startswith("ansible_host="):
                        ip = part.split("=")[1]
                        ips.append(ip)
                        print(f"✅ Resolved IP for {master}: {ip}")
    return ips

def generate_group_vars(cluster_yaml: dict, inventory_path: str, output_path: str):
    master_ips = resolve_master_ips(inventory_path)
    print(f"🌐 Final master IP list: {master_ips}")
    first_ip = master_ips[0] if master_ips else "0.0.0.0"
    rke2_servers = [f"https://{first_ip}:9345"]
    tls_san_list = master_ips

    data = {
        "rke2_version": cluster_yaml.get("kubernetesVersion", "v1.33.1+rke2r1"),
        "rke2_token": cluster_yaml.get("token", "default-token"),
        #"rke2_cni": cluster_yaml.get("cni", "cilium"),
        "rke2_cni": [],
        "rke2_servers": rke2_servers,
        "rke2_tls_san": tls_san_list,
        "rke2_custom_manifests": ['cilium.yaml'],
        "rke2_disable": ['rke2-canal', 'rke2-coredns', 'rke2-ingress-nginx', 'rke2-metrics-server'],
        "rke2_download_kubeconf": True,
    }

    with open(output_path, "w") as f:
        yaml.dump(data, f, default_flow_style=False)
    print(f"📄 Group vars written to: {output_path}")
