import typer
app = typer.Typer()

@app.command("cluster")
def summary_cluster(name: str = typer.Option(..., help="Cluster name")):
    """Get a summarized view of a cluster's state."""
    print(f"🧾 Summary of cluster: {name}")