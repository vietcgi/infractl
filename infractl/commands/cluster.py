import os
import time
import subprocess
import typer

cluster_app = typer.Typer()

@cluster_app.command("launch")
def launch_cluster(
    region: str = typer.Option(..., help="Cluster region"),
    env: str = typer.Option(..., help="Cluster environment"),
    name: str = typer.Option(..., help="Cluster name"),
    force_refresh_ips: bool = typer.Option(False, help="Force refresh inventory IPs"),
    skip_bootstrap: bool = typer.Option(False, help="Skip ArgoCD bootstrap step")
):
    """Full launch flow: provision → install RKE2 → bootstrap ArgoCD"""
    print(f"🚀 Launching cluster {name} in {region}/{env}...")

    from infractl.modules import provision_multipass, install_rke2, bootstrap

    provision_multipass.provision(name=name, refresh_only=force_refresh_ips)
    install_rke2.install(region=region, env=env, name=name, force_refresh_ips=force_refresh_ips)

    # ✅ Set kubeconfig so kubectl works
    default_path = f"{os.getenv('HOME')}/.kube/rke2-{name}.yaml"
    fallback_path = "/etc/rancher/rke2/rke2.yaml"

    if os.path.exists(default_path):
        kubeconfig_path = default_path
    elif os.path.exists(fallback_path):
        kubeconfig_path = fallback_path
    else:
        raise FileNotFoundError(f"❌ kubeconfig not found at: {default_path} or {fallback_path}")

    os.environ["KUBECONFIG"] = kubeconfig_path
    print(f"✅ Using kubeconfig: {kubeconfig_path}")

    # ✅ Wait for Kubernetes API to be ready
    print("⏳ Waiting for Kubernetes API to become available...")
    for _ in range(60):
        result = subprocess.run(["kubectl", "get", "nodes"], capture_output=True)
        if result.returncode == 0:
            print("✅ Kubernetes API is ready.")
            break
        time.sleep(5)
    else:
        raise RuntimeError("❌ Kubernetes API did not become ready in time.")

    if not skip_bootstrap:
        bootstrap.install_argocd()

@cluster_app.command("provision")
def provision_multipass_command(
    name: str = typer.Option(..., help="Cluster name")
):
    """Provision a Multipass node."""
    from infractl.modules import provision_multipass
    provision_multipass.provision(name=name)

@cluster_app.command("install-rke2")
def install_rke2_command(
    region: str = typer.Option(..., help="Cluster region"),
    env: str = typer.Option(..., help="Environment"),
    name: str = typer.Option(..., help="Cluster name")
):
    """Install RKE2 on a target cluster."""
    from infractl.modules import install_rke2
    install_rke2.install(region=region, env=env, name=name)

@cluster_app.command("init")
def init_cluster(
    region: str = typer.Option(..., help="Cluster region"),
    env: str = typer.Option(..., help="Environment"),
    name: str = typer.Option(..., help="Cluster name"),
    clean: bool = typer.Option(False, help="Clean before init")
):
    """Initialize ArgoCD and cluster inventory."""
    from infractl.modules import bootstrap
    print(f"Initializing cluster {name} in {region}/{env}, clean={clean}")
    bootstrap.install_argocd()

@cluster_app.command("list")
def list_clusters():
    """List all registered clusters."""
    from infractl import registry
    clusters = registry.load_registry()
    for name, info in clusters.items():
        typer.echo(f"{name}: {info['config']}")

@cluster_app.command("get")
def get_cluster(name: str = typer.Option(..., help="Cluster name")):
    """Get cluster config and metadata."""
    from infractl import registry
    clusters = registry.load_registry()
    if name in clusters:
        typer.echo(clusters[name])
    else:
        typer.echo(f"❌ Cluster '{name}' not found.")

@cluster_app.command("delete")
def delete_cluster(name: str = typer.Option(..., help="Base name of the cluster")):
    confirm = typer.confirm(f"Are you sure you want to delete the cluster '{name}'?", default=False)
    if not confirm:
        print("❌ Deletion cancelled.")
        raise typer.Exit()
    """Delete all multipass VMs for a cluster and purge them."""
    for role in ["master", "worker"]:
        vm_name = f"{name}-{role}"
        print(f"🗑️  Deleting Multipass VM → {vm_name}")
        try:
            subprocess.run(["multipass", "delete", vm_name], check=True)
        except subprocess.CalledProcessError:
            print(f"⚠️  {vm_name} may not exist or was already deleted.")

    print("🧹 Purging deleted instances...")
    subprocess.run(["multipass", "purge"], check=True)
    print("✅ Cluster deleted and purged.")

app = cluster_app
