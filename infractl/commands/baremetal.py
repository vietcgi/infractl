"""
Baremetal server management commands.
"""
import typer
from pathlib import Path
from typing import Optional, List
import yaml
import time
from datetime import datetime

from infractl.modules.maas import get_maas_client

# Create the Typer app
app = typer.Typer(help="Manage baremetal servers in a cluster")

def reinstall_baremetal_cluster(
    name: str,
    region: str,
    env: str,
    config_dir: Path,
    distro_series: str,
    hwe_kernel: str
) -> None:
    """Reinstall all baremetal servers in a cluster."""
    # Construct the path to the cluster config
    cluster_config_path = config_dir / "rke2" / region / env / name / "cluster.yaml"
    
    if not cluster_config_path.exists():
        typer.echo(f"❌ Cluster config not found at {cluster_config_path}", err=True)
        raise typer.Exit(1)
    
    # Load the cluster config
    with open(cluster_config_path, 'r') as f:
        cluster_config = yaml.safe_load(f)
    
    if cluster_config.get('server_type') != 'baremetal':
        typer.echo("❌ This command only works with baremetal clusters", err=True)
        raise typer.Exit(1)
    
    # Get the list of servers to reinstall
    servers: List[str] = []
    if 'masters' in cluster_config:
        if isinstance(cluster_config['masters'], list):
            servers.extend([m['name'] if isinstance(m, dict) else m for m in cluster_config['masters']])
    
    if 'agents' in cluster_config and isinstance(cluster_config['agents'], list):
        for agent in cluster_config['agents']:
            if isinstance(agent, dict) and 'name' in agent:
                servers.append(agent['name'])
    
    if not servers:
        typer.echo("❌ No servers found in cluster config", err=True)
        raise typer.Exit(1)
    
    # Initialize MAAS client
    maas = get_maas_client()
    if not maas:
        typer.echo(
            "❌ Failed to initialize MAAS client. Please provide credentials via:\n"
            "  1. Environment variables (MAAS_API_URL, MAAS_API_KEY)\n"
            "  2. .env file in the project root\n"
            "  3. cluster.yaml config file"
        )
        raise typer.Exit(1)
    
    # Reinstall each server
    typer.echo(f"🚀 Starting reinstallation of {len(servers)} servers in cluster {name}")
    
    success_count = 0
    for server in servers:
        typer.echo(f"\n🔧 Processing server: {server}")
        try:
            # Find the machine by hostname
            machine = maas.get_machine_by_hostname(server)
            if not machine:
                typer.echo(f"  ❌ Server {server} not found in MAAS")
                continue
                
            system_id = machine['system_id']
            
            # Release the machine
            typer.echo(f"  🔄 Releasing {server}...")
            if not maas.release_machine(system_id, f"Reinstalling as part of cluster {name} reinstallation"):
                typer.echo(f"  ❌ Failed to release {server}")
                continue
                
            # Simple wait (in a real implementation, you'd want to poll the status)
            time.sleep(5)
            
            # Deploy the machine
            typer.echo(f"  🚀 Deploying {server} with {distro_series}...")
            if maas.deploy_machine(
                system_id=system_id,
                distro_series=distro_series,
                hwe_kernel=hwe_kernel
            ):
                typer.echo(f"  ✅ Successfully started reinstallation of {server}")
                success_count += 1
            else:
                typer.echo(f"  ❌ Failed to deploy {server}")
                
        except Exception as e:
            typer.echo(f"  ❌ Error processing {server}: {str(e)}", err=True)
    
    # Print summary
    typer.echo(f"\n✅ Successfully reinstalled {success_count}/{len(servers)} servers")
    if success_count < len(servers):
        typer.echo("⚠️  Some servers failed to reinstall. Check the logs above for details.")
        raise typer.Exit(1)

@app.command()
def reinstall(
    name: str = typer.Argument(..., help="Cluster name"),
    region: str = typer.Option("us-west", "--region", "-r", help="Cluster region"),
    env: str = typer.Option("dev", "--env", "-e", help="Cluster environment"),
    config_dir: Path = typer.Option(
        "clusters",
        "--config-dir",
        "-c",
        help="Path to clusters directory",
        exists=True,
        file_okay=False,
        dir_okay=True,
        resolve_path=True,
    ),
    distro_series: str = typer.Option(
        "focal",
        "--os",
        "-o",
        help="Ubuntu release to install (e.g., 'focal', 'jammy')",
    ),
    hwe_kernel: str = typer.Option(
        "ga-20.04",
        "--kernel",
        "-k",
        help="HWE kernel to use (e.g., 'ga-20.04', 'hwe-22.04')",
    ),
):
    """
    Reinstall all baremetal servers in a cluster.
    
    This will reinstall all servers in the specified cluster with the specified OS.
    """
    reinstall_baremetal_cluster(
        name=name,
        region=region,
        env=env,
        config_dir=config_dir,
        distro_series=distro_series,
        hwe_kernel=hwe_kernel
    )

def main():
    """Entry point for the baremetal module."""
    app()

if __name__ == "__main__":
    main()
