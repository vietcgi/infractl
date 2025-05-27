# infractl/modules/install_rke2.py
import os
import yaml
import logging
import subprocess
import time
from pathlib import Path
import paramiko
from infractl.modules.generate_group_vars import generate_group_vars
from infractl.modules.provision_multipass import provision
from infractl.modules import addons


logging.basicConfig(level=logging.INFO, format='🔧 %(message)s')

def extract_master_ip_from_inventory(inventory_file: str) -> str:
    with open(inventory_file, 'r') as file:
        lines = file.readlines()
    inside_masters_block = False
    for line in lines:
        line = line.strip()
        if line == "[masters]":
            inside_masters_block = True
            continue
        if inside_masters_block:
            if line == "" or line.startswith("["):
                break
            if "ansible_host=" in line:
                return line.split("ansible_host=")[-1].split()[0]
            return line.split()[0]
    raise Exception("❌ Could not find master IP in inventory under [masters]")

def copy_kubeconfig_with_ssh(master_ip: str, remote_path: str, local_path: Path):
    ssh_key = os.path.expanduser(os.getenv("SSH_PRIVATE_KEY", "~/.ssh/id_rsa"))
    ssh_user = os.getenv("SSH_USERNAME", "ubuntu")

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(master_ip, username=ssh_user, key_filename=ssh_key)

    stdin, stdout, _ = ssh.exec_command(f"sudo cat {remote_path}")
    kubeconfig = stdout.read().decode()
    ssh.close()

    kubeconfig = kubeconfig.replace("127.0.0.1", master_ip).replace("localhost", master_ip)

    local_path.parent.mkdir(parents=True, exist_ok=True)
    with open(local_path, "w") as f:
        f.write(kubeconfig)
    logging.info(f"✅ Kubeconfig saved and patched at: {local_path}")

def wait_for_kubernetes_api(kubeconfig_path: Path, timeout: int = 180):
    os.environ["KUBECONFIG"] = str(kubeconfig_path)
    logging.info("⏳ Waiting for Kubernetes API to become available...")
    for _ in range(timeout // 5):
        result = subprocess.run(["kubectl", "get", "nodes"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if result.returncode == 0:
            logging.info("✅ Kubernetes API is ready.")
            return
        time.sleep(5)
    raise TimeoutError("❌ Timed out waiting for Kubernetes API to be ready")

def install(
    region: str,
    env: str,
    name: str,
    force_refresh_ips: bool = False,
    skip_argocd: bool = False,
    install_flux: bool = False,
    install_fleet: bool = False
):
    logging.info(f"Installing RKE2 for cluster '{name}' in region '{region}' and environment '{env}'")

    # Platform-aware cluster.yaml resolution
    cluster_yaml_path = None
    for platform in ["rke2", "eks", "aks", "gke"]:
        path = Path(f"clusters/{platform}/{region}/{env}/{name}/cluster.yaml")
        if path.exists():
            cluster_yaml_path = path
            break

    if not cluster_yaml_path or not cluster_yaml_path.exists():
        raise FileNotFoundError("❌ Cluster config not found in clusters/<platform>/<region>/<env>/<name>/cluster.yaml")

    with open(cluster_yaml_path, 'r') as file:
        cluster_config = yaml.safe_load(file)

    inventory_file = cluster_config.get("inventory", f"ansible/hosts-{name}.ini")
    group_vars_file = f"ansible/group_vars/{name}.yml"

    provision(config=cluster_config, refresh_only=force_refresh_ips)
    generate_group_vars(cluster_yaml=cluster_config, inventory_path=inventory_file, output_path=group_vars_file)

    ansible_cmd = [
        "ansible-playbook",
        "-i", inventory_file,
        "ansible/playbook.yml",
        "--extra-vars", f"@{group_vars_file}"
    ]

    env_vars = os.environ.copy()
    env_vars["ANSIBLE_HOST_KEY_CHECKING"] = "False"
    result = subprocess.run(ansible_cmd, env=env_vars)
    if result.returncode != 0:
        raise Exception("❌ RKE2 installation failed")

    logging.info("✅ RKE2 installation complete.")

    master_ip = extract_master_ip_from_inventory(inventory_file)
    remote_kubeconfig = "/etc/rancher/rke2/rke2.yaml"
    local_kubeconfig = Path.home() / f".kube/rke2-{name}.yaml"
    copy_kubeconfig_with_ssh(master_ip, remote_kubeconfig, local_kubeconfig)
    wait_for_kubernetes_api(local_kubeconfig)

    if install_fleet:
        print("⚙️  --install-fleet flag detected, installing Fleet GitOps.")
        addons.install_fleet()

    elif install_flux:
        print("⚙️  --install-flux flag detected, installing FluxCD GitOps.")
        addons.install_flux()

    elif not skip_argocd:
        print("⚙️  Installing ArgoCD...")
        # addons.bootstrap_gitops_stack(kubeconfig_path=str(local_kubeconfig))
        addons.bootstrap_gitops_stack(
            env=env,
            install_flux=install_flux,
            install_fleet=install_fleet,
            skip_argocd=skip_argocd
        )

