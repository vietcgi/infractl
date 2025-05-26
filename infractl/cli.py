import typer
from infractl.commands import (
    create, reset, delete, status,
    sync, summary, validate, plugin
)

app = typer.Typer()
app.add_typer(create.app, name="create")
app.add_typer(reset.app, name="reset")
app.add_typer(delete.app, name="delete")
app.add_typer(status.app, name="status")
app.add_typer(sync.app, name="sync")
app.add_typer(summary.app, name="summary")
app.add_typer(validate.app, name="validate")
app.add_typer(plugin.app, name="plugin")

if __name__ == "__main__":
    app()