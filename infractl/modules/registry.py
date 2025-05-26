import os
import json

REGISTRY_FILE = "clusters/cluster-registry.json"

def load_registry():
    if os.path.exists(REGISTRY_FILE):
        with open(REGISTRY_FILE, "r") as f:
            return json.load(f)
    return {}

def save_registry(data):
    with open(REGISTRY_FILE, "w") as f:
        json.dump(data, f, indent=2)

def register_entry(name, config_path, purpose=None, cluster_type=None, tags=None):
    registry = load_registry()
    registry[name] = {
        "config": config_path,
        "purpose": purpose,
        "type": cluster_type,
        "tags": tags or {}
    }
    save_registry(registry)
