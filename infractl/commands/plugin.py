import typer
app = typer.Typer()

@app.command("install")
def plugin_install(name: str = typer.Option(..., help="Plugin name")):
    """Install a new CLI plugin."""
    print(f"🔌 Installing plugin: {name}")