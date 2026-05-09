import typer


app = typer.Typer(help="OpenClaw research triage CLI.")


@app.callback()
def main() -> None:
    """OpenClaw research triage CLI."""
