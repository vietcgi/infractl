import os
import subprocess
import pytest
import yaml

def run_cli_command(cmd):
    return subprocess.run(["python", "infractl/cli.py"] + cmd.split(), capture_output=True, text=True)

def test_cluster_init_dry_run(tmp_path):
    cluster_yaml = tmp_path / "cluster.yaml"
    cluster_yaml.write_text("""
name: test-cluster
purpose: test
type: mock
inventory: /tmp/fake-inventory.ini
kubeconfig: /tmp/fake-kubeconfig.yaml
apps:
- /tmp/fake-app.yaml
""")

    result = run_cli_command(f"cluster init --name test-cluster --check False")
    assert "Initializing cluster" in result.stdout

def test_register_cluster(tmp_path):
    registry_file = "clusters/cluster-registry.json"
    cluster_yaml = tmp_path / "cluster.yaml"
    cluster_yaml.write_text("""
name: test-cluster
purpose: test
type: static
kubeconfig: /tmp/fake.yaml
apps: []
""")

    result = run_cli_command(f"cluster register --file {cluster_yaml}")
    assert "test-cluster" in result.stdout

    # Cleanup registry
    import json
    with open(registry_file, "r") as f:
        reg = json.load(f)
    reg.pop("test-cluster", None)
    with open(registry_file, "w") as f:
        json.dump(reg, f, indent=2)
