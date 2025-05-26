import typer
import subprocess
import os
import yaml
from pathlib import Path
from datetime import datetime

app = typer.Typer()

@app.command("cluster")
def delete_cluster_cmd(
    name: str = typer.Option(..., help="Cluster name"),
    region: str = typer.Option("us-west", help="Cluster region"),
    env: str = typer.Option("dev", help="Cluster environment"),
    platform: str = typer.Option(None, help="Cluster platform (e.g. rke2, eks, aks)"),
    dry_run: bool = typer.Option(False, help="Show what would be deleted without removing")
):
    cluster_id = f"{region}-{env}-{name}".lower().replace("_", "-")
    cluster_dir = None
    config_path = None

    # Try to resolve full path to cluster.yaml
    if platform:
        cluster_dir = Path(f"clusters/{platform}/{region}/{env}/{name}")
        config_path = cluster_dir / "cluster.yaml"
    else:
        for possible_platform in ["rke2", "eks", "aks", "gke"]:
            test_path = Path(f"clusters/{possible_platform}/{region}/{env}/{name}/cluster.yaml")
            if test_path.exists():
                platform = possible_platform
                cluster_dir = test_path.parent
                config_path = test_path
                break

    if not platform or not config_path or not config_path.exists():
        print("❌ Could not locate cluster.yaml or determine platform. Use --platform if needed.")
        raise typer.Exit(code=1)

    with open(config_path) as f:
        config = yaml.safe_load(f)

    confirm = typer.confirm(f"Are you sure you want to delete cluster '{cluster_id}'?", default=False)
    if not confirm:
        print("❌ Deletion cancelled.")
        raise typer.Exit()

    # Gather nodes
    nodes = config.get("masters", []) + config.get("agents", [])
    if not nodes:
        print("🔍 No nodes defined. Trying to discover from Multipass...")
        try:
            result = subprocess.run(["multipass", "list"], capture_output=True, text=True, check=True)
            for line in result.stdout.splitlines():
                if cluster_id in line:
                    vm_name = line.split()[0]
                    nodes.append({"name": vm_name})
        except subprocess.CalledProcessError:
            print("⚠️  Failed to list Multipass VMs.")

    for node in nodes:
        vm_name = node["name"]
        print(f"🗑️ Deleting Multipass VM → {vm_name}")
        if dry_run:
            print(f"🧪 Would delete multipass VM: {vm_name}")
        else:
            try:
                subprocess.run(["multipass", "delete", vm_name], check=True)
            except subprocess.CalledProcessError:
                print(f"⚠️  {vm_name} may not exist or was already deleted.")

    if not dry_run:
        print("🧹 Purging deleted instances...")
        subprocess.run(["multipass", "purge"], check=True)

    # Delete auxiliary files
    paths_to_delete = [
        f"ansible/group_vars/{cluster_id}.yml",
        f"ansible/group_vars/{name}.yml",
        f"ansible/hosts-{cluster_id}.ini",
        f"ansible/hosts-{name}.ini",
        f"~/.kube/rke2-{cluster_id}.yaml",
        f"~/.kube/rke2-{name}.yaml",
    ]

    for path in paths_to_delete:
        path = os.path.expanduser(path)
        if os.path.exists(path):
            if dry_run:
                print(f"🧪 Would delete: {path}")
            else:
                os.remove(path)
                print(f"🧹 Removed file: {path}")
        else:
            print(f"🔍 File not found (skipped): {path}")

    # Update cluster.yaml status
    if config_path.exists() and not dry_run:
        config.setdefault("status", {})
        config["status"].update({
            "provisioned": False,
            "deleted": True,
            "last_updated": datetime.utcnow().isoformat()
        })
        with open(config_path, "w") as f:
            yaml.dump(config, f)
        print(f"📝 Updated cluster status in {config_path}")

    print("✅ Cluster deletion complete.")
