
import json
from pathlib import Path

REGISTRY_PATH = Path("clusters/cluster-registry.json")

def load_registry():
    if REGISTRY_PATH.exists():
        with open(REGISTRY_PATH, "r") as f:
            return json.load(f)
    return {}

def save_registry(data):
    with open(REGISTRY_PATH, "w") as f:
        json.dump(data, f, indent=2)
