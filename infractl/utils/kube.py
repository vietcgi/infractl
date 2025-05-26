
import os
from pathlib import Path
from kubernetes import config

def load_kubeconfig(path: str = None) -> str:
    """
    Load the kubeconfig from a given path or from the KUBECONFIG_CONTENT env var.
    Returns the actual path used to load the kubeconfig.
    """
    # CI/CD secret-based loading
    if "KUBECONFIG_CONTENT" in os.environ:
        temp_path = "/tmp/ci-kubeconfig.yaml"
        with open(temp_path, "w") as f:
            f.write(os.environ["KUBECONFIG_CONTENT"])
        config.load_kube_config(config_file=temp_path)
        return temp_path

    # Local path loading
    if path:
        resolved = Path(os.path.expanduser(path)).resolve()
        if not resolved.exists():
            raise FileNotFoundError(f"❌ Kubeconfig not found: {resolved}")
        config.load_kube_config(config_file=str(resolved))
        return str(resolved)

    raise ValueError("No kubeconfig path provided and KUBECONFIG_CONTENT is not set.")
