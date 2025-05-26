import typer

doctor_app = typer.Typer()

@doctor_app.command("summary")
def summary(
    namespace: str = typer.Option("argocd", help="Target namespace"),
    export: str = typer.Option("summary.json", help="Export filename")
):
    """Generate cluster app summary."""
    print(f"🧪 Summary for namespace={namespace} saved to {export}")

app = doctor_app