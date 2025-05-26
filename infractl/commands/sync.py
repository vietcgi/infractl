import typer
app = typer.Typer()

@app.command("apps")
def sync_apps(env: str = typer.Option(..., help="Environment name")):
    """Sync all GitOps apps manually."""
    print(f"🔁 Syncing apps in environment: {env}")