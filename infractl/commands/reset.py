
import typer
from infractl.modules import provision_multipass, install_rke2

app = typer.Typer()

@app.command("cluster")
def reset_cluster_cmd(
    name: str = typer.Option(..., help="Cluster name"),
    region: str = typer.Option("us-west", help="Cluster region"),
    env: str = typer.Option("dev", help="Cluster environment"),
    skip_argocd: bool = typer.Option(False, help="Skip ArgoCD installation"),
    install_flux: bool = typer.Option(False, help="Install Flux instead of ArgoCD"),
):
    print(f"🔁 Resetting cluster {name} in {region}/{env}")
    provision_multipass.provision(name=name, refresh_only=True)
    install_rke2.create_cluster(
        name=name,
        region=region,
        env=env,
        skip_argocd=skip_argocd,
        install_flux=install_flux,
        force_refresh_ips=True,
    )
