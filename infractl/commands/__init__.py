import typer
from . import create, reset, delete, status, sync, summary, validate, plugin, reinstall, deploy
from .cluster import app as cluster_app

# Create the main app
app = typer.Typer()

# Add subcommands
app.add_typer(cluster_app, name="cluster")
app.add_typer(reinstall.app, name="reinstall")
app.add_typer(deploy.app, name="deploy")

# Export the app for use in cli.py
__all__ = ['app']