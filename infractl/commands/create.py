
import os
import time
import subprocess
import typer
import yaml
import logging
from pathlib import Path
from jsonschema import validate, ValidationError
from infractl.modules import provision_multipass, install_rke2, bootstrap

app = typer.Typer()

CLUSTER_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "region": {"type": "string"},
        "env": {"type": "string"},
        "purpose": {"type": "string"},
        "type": {"type": "string"},
        "cluster_type": {"type": "string"},
        "server_type": {"type": "string"},
        "ssh_key": {"type": "string"},
        "os": {"type": "string"},
        "kubernetes_version": {"type": "string"},
        "kubeconfig": {"type": "string"},
        "inventory": {"type": "string"},
        "apps": {"type": "array"},
        "masters": {"type": "array"},
        "agents": {"type": "array"},
        "tags": {"type": "object"}
    },
    "required": ["name", "region", "env"]
}

@app.command("cluster")
def create_cluster_cmd(
    name: str = typer.Option(..., help="Cluster name"),
    region: str = typer.Option("us-west", help="Cluster region"),
    env: str = typer.Option("dev", help="Cluster environment"),
    platform: str = typer.Option(None, help="Cluster platform (e.g. rke2, eks, aks)"),
    skip_argocd: bool = typer.Option(False, help="Skip ArgoCD installation"),
    install_flux: bool = typer.Option(False, help="Install FluxCD instead of ArgoCD"),
    install_fleet: bool = typer.Option(False, help="Install Fleet GitOps instead of ArgoCD"),
    force_refresh_ips: bool = typer.Option(False, help="Force refresh inventory IPs")
):
    logging.basicConfig(level=logging.INFO, format="🔧 %(message)s")
    cluster_id = f"{region}-{env}-{name}".lower().replace("_", "-")
    logging.info(f"🚀 Creating cluster {cluster_id}...")

    cluster_dir = None
    cluster_path = None

    # Platform resolution
    if platform:
        cluster_path = Path(f"clusters/{platform}/{region}/{env}/{name}/cluster.yaml")
        cluster_dir = cluster_path.parent
    else:
        for candidate in ["rke2", "eks", "aks", "gke"]:
            test_path = Path(f"clusters/{candidate}/{region}/{env}/{name}/cluster.yaml")
            if test_path.exists():
                platform = candidate
                cluster_path = test_path
                cluster_dir = test_path.parent
                break

    if not platform or not cluster_path or not cluster_path.exists():
        raise typer.Exit(f"❌ Cluster definition not found. Use --platform or verify path: clusters/<platform>/{region}/{env}/{name}/cluster.yaml")

    with open(cluster_path) as f:
        cluster_config = yaml.safe_load(f)

    try:
        validate(instance=cluster_config, schema=CLUSTER_SCHEMA)
    except ValidationError as ve:
        raise typer.Exit(code=1, message=f"❌ YAML validation error: {ve.message}")

    if any("count" in item for item in cluster_config.get("masters", [])):
        logging.warning("❌ YAML is not normalized — contains master count.")
        raise typer.Exit("Run: python -m infractl.utils.normalize ... and fix YAML.")

    if any("count" in item for item in cluster_config.get("agents", [])):
        logging.warning("❌ YAML is not normalized — contains agent count.")
        raise typer.Exit("Run: python -m infractl.utils.normalize ... and fix YAML.")

    logging.info(f"📄 Loaded config from {cluster_path}")
    logging.info("✅ YAML schema validated")

    ssh_key = os.path.expanduser(cluster_config.get("ssh_key", "~/.ssh/id_rsa"))
    kubeconfig_path = os.path.expanduser(cluster_config["kubeconfig"])
    os.environ["KUBECONFIG"] = kubeconfig_path

    if not cluster_config.get("masters"):
        raise ValueError("❌ No masters defined")
    if not cluster_config.get("agents"):
        raise ValueError("❌ No agents defined")

    logging.info("🚧 Starting VM provisioning...")
    provision_multipass.provision(config=cluster_config, refresh_only=force_refresh_ips)

    logging.info("🔧 Installing RKE2...")

    if install_flux and install_fleet:
        raise typer.BadParameter("❌ You can only install one GitOps engine: --install-flux OR --install-fleet, not both.")

    install_rke2.install(
        region=region,
        env=env,
        name=name,
        force_refresh_ips=force_refresh_ips,
        skip_argocd=skip_argocd,
        install_flux=install_flux,
        install_fleet=install_fleet
    )

    logging.info("✅ Cluster provisioning complete.")
