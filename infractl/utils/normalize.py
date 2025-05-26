# infractl/utils/normalize.py
import yaml
import os
from pathlib import Path

def normalize_cluster_yaml(path: str):
    with open(path) as f:
        data = yaml.safe_load(f)

    name = data["name"]
    region = data["region"]
    env = data["env"]
    cluster_id = f"{region}-{env}-{name}".lower().replace("_", "-")

    # Normalize kubeconfig and inventory
    data["kubeconfig"] = f"~/.kube/rke2-{cluster_id}.yaml"
    data["inventory"] = f"ansible/hosts-{cluster_id}.ini"

    # Expand masters with auto-merge of count + name entries
    master_defs = []
    if data.get("masters"):
        merged = {}
        for item in data["masters"]:
            if "count" in item:
                merged["count"] = item["count"]
            if "name" in item:
                merged["name"] = item["name"]
            if set(item.keys()) - {"count", "name"}:
                raise ValueError(f"❌ Invalid key in masters entry: {item}")
        if "count" in merged:
            base_name = merged.get("name", "master")
            for i in range(int(merged["count"])):
                master_defs.append({"name": f"{cluster_id}-{base_name}-{i}"})
        elif "name" in merged:
            final_name = merged["name"]
            if not final_name.startswith(cluster_id):
                final_name = f"{cluster_id}-{final_name}"
            master_defs.append({"name": final_name})
    data["masters"] = master_defs

    # Expand agents with auto-merge of count + name entries
    agent_defs = []
    if data.get("agents"):
        merged = {}
        for item in data["agents"]:
            if "count" in item:
                merged["count"] = item["count"]
            if "name" in item:
                merged["name"] = item["name"]
            if set(item.keys()) - {"count", "name"}:
                raise ValueError(f"❌ Invalid key in agents entry: {item}")
        if "count" in merged:
            base_name = merged.get("name", "worker")
            for i in range(int(merged["count"])):
                agent_defs.append({"name": f"{cluster_id}-{base_name}-{i}"})
        elif "name" in merged:
            final_name = merged["name"]
            if not final_name.startswith(cluster_id):
                final_name = f"{cluster_id}-{final_name}"
            agent_defs.append({"name": final_name})
    data["agents"] = agent_defs

    # Write to temp location instead of overwriting original
    normalized_path = Path("/tmp") / (Path(path).stem + ".normalized.yaml")
    with open(normalized_path, "w") as out:
        yaml.dump(data, out, sort_keys=False)
    print(f"✅ Normalized template written to: {normalized_path}\n👉 Review it, update your original cluster YAML, and re-run create.")

# Optional CLI entrypoint
if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        print("Usage: python -m infractl.utils.normalize <path-to-cluster.yaml>")
        sys.exit(1)
    normalize_cluster_yaml(sys.argv[1])
