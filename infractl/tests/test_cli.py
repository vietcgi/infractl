import subprocess
import pytest

def run_cli_command(cmd):
    return subprocess.run(["python", "infractl/cli.py"] + cmd.split(), capture_output=True, text=True)

def test_help():
    result = run_cli_command("--help")
    assert "Usage" in result.stdout

def test_cluster_commands_exist():
    result = run_cli_command("cluster --help")
    assert "register" in result.stdout
    assert "list" in result.stdout

def test_sync_help():
    result = run_cli_command("sync --help")
    assert "--app" in result.stdout

def test_summary_help():
    result = run_cli_command("summary --help")
    assert "--namespace" in result.stdout
