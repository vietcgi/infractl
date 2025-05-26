import typer
app = typer.Typer()

@app.command("cluster")
def status_cluster(name: str = typer.Option(..., help="Cluster name")):
    """Show current health of a cluster."""
    print(f"📡 Status for cluster: {name}")