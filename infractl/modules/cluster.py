import typer
from infractl.modules.install_rke2 import install
from infractl.modules.lifecycle import reset_cluster, delete_cluster

cluster_app = typer.Typer()

@cluster_app.command("install")
def install_command(
    name: str = typer.Option(..., help="Cluster name"),
    region: str = typer.Option("us-west", help="Cluster region"),
    env: str = typer.Option("dev", help="Cluster environment"),
    skip_argocd: bool = typer.Option(False, help="Skip ArgoCD installation"),
    install_flux: bool = typer.Option(False, help="Install Flux instead of ArgoCD"),
    force_refresh_ips: bool = typer.Option(False, help="Force refresh inventory IPs")
):
    install(region=region, env=env, name=name, skip_argocd=skip_argocd, install_flux=install_flux, force_refresh_ips=force_refresh_ips)

@cluster_app.command("reset")
def reset_cluster_command(
    name: str = typer.Option(..., help="Cluster name"),
    region: str = typer.Option("us-west", help="Cluster region"),
    env: str = typer.Option("dev", help="Cluster environment"),
    skip_argocd: bool = typer.Option(False, help="Skip ArgoCD installation"),
    install_flux: bool = typer.Option(False, help="Install Flux instead of ArgoCD")
):
    reset_cluster(region=region, env=env, name=name, skip_argocd=skip_argocd, install_flux=install_flux)

@cluster_app.command("delete")
def delete_cluster_command(name: str = typer.Option(..., help="Cluster name")):
    delete_cluster(name)
