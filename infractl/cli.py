import typer
import logging
import sys
import os
from typing import Optional, List, Any, Dict
from infractl.commands import (
    create, reset, delete, status,
    sync, summary, validate, plugin, reinstall, deploy
)

# Create a callback for global options
app = typer.Typer()

# Global debug flag
debug = False

# Configure logging
def setup_logging(debug_mode: bool = False):
    """Configure logging based on debug mode."""
    log_level = logging.DEBUG if debug_mode else logging.INFO
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler()
        ]
    )
    # Disable debug logging for noisy libraries
    if not debug_mode:
        logging.getLogger('paramiko').setLevel(logging.WARNING)
        logging.getLogger('urllib3').setLevel(logging.WARNING)

# Add all command groups
app.add_typer(create.app, name="create")
app.add_typer(reset.app, name="reset")
app.add_typer(delete.app, name="delete")
app.add_typer(status.app, name="status")
app.add_typer(sync.app, name="sync")
app.add_typer(summary.app, name="summary")
app.add_typer(validate.app, name="validate")
app.add_typer(plugin.app, name="plugin")
app.add_typer(reinstall.app, name="reinstall")
app.add_typer(deploy.app, name="deploy")

# Global options callback
@app.callback()
def main(
    debug: bool = typer.Option(False, "--debug", "-d", help="Enable debug logging"),
):
    """InfraCTL - Infrastructure Management CLI."""
    global debug_mode
    debug_mode = debug
    setup_logging(debug)
    if debug:
        logging.getLogger().setLevel(logging.DEBUG)
        logging.debug("Debug mode enabled")

if __name__ == "__main__":
    try:
        app()
    except Exception as e:
        if debug_mode:
            import traceback
            logging.error(f"Unhandled exception: {e}\n{traceback.format_exc()}")
        else:
            logging.error(f"Error: {e}")
        sys.exit(1)