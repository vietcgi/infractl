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
    """
    Copy kubeconfig from master node using SSH with passwordless sudo.
    Tries multiple methods to retrieve the kubeconfig file.
    """
    try:
        ssh_key = os.path.expanduser(os.getenv("SSH_PRIVATE_KEY", "~/.ssh/id_rsa"))
        ssh_user = os.getenv("SSH_USERNAME", "ubuntu")
        
        # Verify SSH key exists and has correct permissions
        if not os.path.exists(ssh_key):
            raise FileNotFoundError(f"SSH key not found at {ssh_key}")
        
        # Common kubeconfig locations to try
        kubeconfig_paths = [
            "/etc/rancher/rke2/rke2.yaml",
            "/var/lib/rancher/rke2/server/cred/admin.kubeconfig",
            f"/home/{ssh_user}/.kube/config"
        ]
        
        # If a specific path was provided, try it first
        if remote_path not in kubeconfig_paths:
            kubeconfig_paths.insert(0, remote_path)
        
        ssh_base_cmd = [
            "ssh", "-i", ssh_key,
            "-o", "StrictHostKeyChecking=no",
            "-o", "BatchMode=yes",
            "-o", "ConnectTimeout=10",
            f"{ssh_user}@{master_ip}"
        ]
        
        def run_ssh_command(cmd_parts):
            """Helper to run an SSH command and return (success, output)"""
            full_cmd = ssh_base_cmd + ["--"] + cmd_parts
            try:
                result = subprocess.run(
                    full_cmd,
                    capture_output=True,
                    text=True,
                    check=True
                )
                return True, result.stdout.strip()
            except subprocess.CalledProcessError as e:
                return False, e.stderr
        
        # First, test basic SSH connectivity
        print(f"🔍 Testing SSH connection to {ssh_user}@{master_ip}...")
        success, output = run_ssh_command(["echo", "SSH_TEST_OK"])
        
        if not success or "SSH_TEST_OK" not in output:
            print("❌ SSH test failed")
            if "Permission denied" in output:
                print("🔑 SSH Permission denied. Please verify:")
                print(f"1. The SSH key at {ssh_key} is correct")
                print(f"2. The key is added to the SSH agent: ssh-add {ssh_key}")
                print(f"3. The key is in {ssh_user}'s authorized_keys on the server")
            raise Exception(f"SSH test failed: {output}")
        
        print("🔑 SSH connection successful, searching for kubeconfig...")
        
        # Try each kubeconfig location
        for path in kubeconfig_paths:
            print(f"🔍 Trying to retrieve kubeconfig from {path}...")
            
            # Try with sudo first, then without if that fails
            for use_sudo in [True, False]:
                sudo_prefix = ["sudo", "cat"] if use_sudo else ["cat"]
                success, output = run_ssh_command(sudo_prefix + [path])
                
                if success and "apiVersion" in output:
                    print(f"✅ Found valid kubeconfig at {path}")
                    
                    # Update server address in kubeconfig
                    kubeconfig = output.replace("127.0.0.1", master_ip).replace("localhost", master_ip)
                    
                    # Ensure local directory exists
                    local_path.parent.mkdir(parents=True, exist_ok=True)
                    
                    # Write the kubeconfig
                    with open(local_path, "w") as f:
                        f.write(kubeconfig)
                        
                    print(f"✅ Kubeconfig saved to: {local_path}")
                    return True
                    
        # If we get here, no valid kubeconfig was found
        raise Exception(f"❌ Could not find valid kubeconfig in any standard location. Tried: {', '.join(kubeconfig_paths)}")
        
    except subprocess.CalledProcessError as e:
        print(f"❌ Command failed with exit code {e.returncode}")
        if e.stderr:
            print(f"Error: {e.stderr.strip()}")
        
        print("\n🔧 Troubleshooting steps:")
        print(f"1. Test SSH connection: ssh -i {ssh_key} {ssh_user}@{master_ip}")
        print(f"2. Verify key permissions: chmod 600 {ssh_key}")
        print(f"3. Check key in agent: ssh-add -l | grep $(ssh-keygen -lf {ssh_key} | awk '{{print $2}}')")
        print(f"4. Check server logs: ssh -i {ssh_key} {ssh_user}@{master_ip} 'journalctl -u rke2-server -n 20'")
        
        raise Exception(f"Failed to copy kubeconfig: {str(e)}")
    except Exception as e:
        print(f"❌ Unexpected error: {str(e)}")
        raise

def wait_for_kubernetes_api(kubeconfig_path: Path, timeout: int = 180):
    """Wait for Kubernetes API to become available."""
    print(f"⏳ Waiting for Kubernetes API to be ready (timeout: {timeout}s)...")
    os.environ["KUBECONFIG"] = str(kubeconfig_path)
    start_time = time.time()
    
    while time.time() - start_time < timeout:
        try:
            result = subprocess.run(
                ["kubectl", "get", "nodes", "--no-headers"],
                capture_output=True,
                text=True
            )
            if result.returncode == 0 and result.stdout.strip():
                print("✅ Kubernetes API is ready")
                return True
        except Exception:
            pass
            
        time.sleep(5)
        
    raise TimeoutError(f"Timed out waiting for Kubernetes API after {timeout} seconds")

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

    # For production, skip all auto-generation
    if env == 'prod':
        logging.info("🔒 Production environment detected - skipping VM provisioning and group vars generation")
        if not os.path.exists(inventory_file):
            raise FileNotFoundError(f"Production inventory file not found: {inventory_file}")
        if not os.path.exists(group_vars_file):
            raise FileNotFoundError(f"Production group vars file not found: {group_vars_file}")
    else:
        # Non-production environment - proceed with normal flow
        logging.info("🚀 Starting VM provisioning...")
        provision(config=cluster_config, refresh_only=force_refresh_ips)
        logging.info("📝 Generating group vars...")
        generate_group_vars(cluster_config=cluster_config, inventory_path=inventory_file, output_path=group_vars_file)

    # Get SSH user from environment or default to 'ubuntu'
    ssh_user = os.getenv("SSH_USERNAME", "ubuntu")
    
    ansible_cmd = [
        "ansible-playbook",
        "-i", inventory_file,
        "ansible/playbook.yml",
        "--user", ssh_user,  # Add SSH user to Ansible command
        "--extra-vars", f"@{group_vars_file}",
        "--extra-vars", f"ansible_user={ssh_user}"  # Ensure ansible_user is set
    ]

    env_vars = os.environ.copy()
    env_vars["ANSIBLE_HOST_KEY_CHECKING"] = "False"
    # Add ANSIBLE_REMOTE_USER to environment
    env_vars["ANSIBLE_REMOTE_USER"] = ssh_user
    
    print(f"🔧 Running Ansible with user: {ssh_user}")
    print(f"🔧 Command: {' '.join(ansible_cmd)}")
    
    result = subprocess.run(ansible_cmd, env=env_vars)
    if result.returncode != 0:
        raise Exception("❌ RKE2 installation failed")

    logging.info("✅ RKE2 installation complete.")

    master_ip = extract_master_ip_from_inventory(inventory_file)
    remote_kubeconfig = "/etc/rancher/rke2/rke2.yaml"
    local_kubeconfig = Path.home() / f".kube/rke2-{name}.yaml"
    copy_kubeconfig_with_ssh(master_ip, remote_kubeconfig, local_kubeconfig)
    wait_for_kubernetes_api(local_kubeconfig)

    # Verify kubeconfig exists and is accessible
    if not local_kubeconfig.exists():
        raise FileNotFoundError(f"❌ Kubeconfig not found at {local_kubeconfig}. Cannot proceed with GitOps installation.")
    
    # Set KUBECONFIG in environment for subsequent commands
    os.environ['KUBECONFIG'] = str(local_kubeconfig)
    print(f"🔧 Using kubeconfig: {local_kubeconfig}")
    
    # Handle kubeconfig for both local and GitHub Actions
    is_github_actions = os.environ.get('GITHUB_ACTIONS') == 'true'
    kubeconfig_path = os.environ.get('KUBECONFIG')
    
    if is_github_actions:
        # In GitHub Actions, just set KUBECONFIG environment variable
        print("::set-output name=kubeconfig::%s" % str(local_kubeconfig))
        print("::set-env name=KUBECONFIG::%s" % str(local_kubeconfig))
        print(f"✅ Set KUBECONFIG for GitHub Actions: {local_kubeconfig}")
    else:
        # Local environment setup
        try:
            # Create .kube directory if it doesn't exist
            kube_dir = Path.home() / ".kube"
            kube_dir.mkdir(exist_ok=True, mode=0o700)
            
            # Get the context name from the kubeconfig
            get_context_cmd = ["kubectl", "config", "view", "-o", "jsonpath='{.contexts[0].name}'", "--kubeconfig", str(local_kubeconfig)]
            context_name = subprocess.check_output(get_context_cmd, text=True).strip("'")
            
            # If KUBECONFIG is set or we're in CI, don't modify the default config
            if kubeconfig_path or os.environ.get('CI'):
                print(f"ℹ️  KUBECONFIG is set or in CI mode, not modifying default config")
                print(f"   Using kubeconfig: {kubeconfig_path or local_kubeconfig}")
            else:
                # Default kubeconfig location
                default_config = kube_dir / "config"
                
                if not default_config.exists():
                    # If default config doesn't exist, create it
                    import shutil
                    shutil.copy2(local_kubeconfig, default_config)
                    print(f"✅ Created new kubeconfig at {default_config}")
                else:
                    # Otherwise, merge the new config with the existing one
                    merge_cmd = f"KUBECONFIG={default_config}:{local_kubeconfig} kubectl config view --flatten"
                    with open(default_config.with_suffix('.tmp'), 'w') as f:
                        subprocess.run(merge_cmd, shell=True, check=True, stdout=f, text=True)
                    
                    # Replace the old config with the merged one
                    default_config.with_suffix('.tmp').replace(default_config)
                    print(f"✅ Merged kubeconfig into {default_config}")
                
                # Set the current context
                subprocess.run(["kubectl", "config", "use-context", context_name], check=True)
                print(f"✅ Set current context to '{context_name}'")
        
        except subprocess.CalledProcessError as e:
            print(f"⚠️  Warning: Failed to configure kubeconfig: {e}")
            print("You can set the kubeconfig manually with:")
            print(f"  export KUBECONFIG={local_kubeconfig}")
        
        # Always set KUBECONFIG for the current process
        os.environ['KUBECONFIG'] = str(local_kubeconfig)

    # Install GitOps components if requested
    try:
        if install_fleet:
            print("⚙️  --install-fleet flag detected, installing Fleet GitOps...")
            addons.bootstrap_gitops_stack(
                env=env,
                install_flux=False,
                install_fleet=True,
                skip_argocd=True,
                kubeconfig_path=str(local_kubeconfig)
            )
            print("✅ Fleet installation completed successfully")
        elif install_flux:
            print("⚙️  --install-flux flag detected, installing FluxCD GitOps...")
            addons.bootstrap_gitops_stack(
                env=env,
                install_flux=True,
                install_fleet=False,
                skip_argocd=True,
                kubeconfig_path=str(local_kubeconfig)
            )
            print("✅ FluxCD installation completed successfully")
        elif not skip_argocd:
            print("⚙️  Installing GitOps stack with ArgoCD...")
            addons.bootstrap_gitops_stack(
                env=env,
                install_flux=False,
                install_fleet=False,
                skip_argocd=skip_argocd,
                kubeconfig_path=str(local_kubeconfig),
                cluster=name
            )
            print("✅ ArgoCD installation completed successfully")
            
    except Exception as e:
        print(f"⚠️  An error occurred during GitOps installation: {e}")
        raise
