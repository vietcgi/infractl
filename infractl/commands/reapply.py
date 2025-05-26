import typer

reapply_app = typer.Typer()

@reapply_app.command("reapply-matched")
def reapply_matched(
    region: str = typer.Option("", help="Cluster region"),
    env: str = typer.Option("", help="Environment"),
    dry_run: bool = typer.Option(False, help="Perform a dry-run")
):
    """Reapply apps to matched clusters."""
    print(f"🔁 Reapplying (dry_run={dry_run}) for region={region}, env={env}")

app = reapply_app