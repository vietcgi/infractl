import typer
app = typer.Typer()

@app.command("cluster")
def validate_cluster(name: str = typer.Option(..., help="Cluster name")):
    """Validate cluster manifests against schema."""
    print(f"🔍 Validating cluster: {name}")