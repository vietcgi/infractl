import yaml
import os
from modules import provision, bootstrap
from modules.utils import logger
from modules.registry import register_entry

def register_cluster(file_path):
    if not os.path.exists(file_path):
        return {"status": "error", "message": f"File not found: {file_path}"}

    with open(file_path, "r") as f:
        cluster_config = yaml.safe_load(f)

    cluster_name = cluster_config.get("name")
    kubeconfig = cluster_config.get("kubeconfig")
    app_paths = cluster_config.get("apps", [])

    logger.info(f"📦 Registering cluster: {cluster_name}")
    logger.info(f"🔑 Using kubeconfig: {kubeconfig}")

    # Step 1: Provision infra (if defined by inventory)
    inventory_path = cluster_config.get("inventory")
    if inventory_path:
        logger.info(f"🛠 Provisioning with inventory: {inventory_path}")
        provision.run(inventory=inventory_path)

    # Step 2: Set KUBECONFIG
    os.environ["KUBECONFIG"] = kubeconfig

    # Step 3: Install ArgoCD (if not already)
    logger.info("🚀 Installing ArgoCD...")
    bootstrap.run(cluster_yaml="placeholder", clean=False)  # Simulated; modify if needed

    # Step 4: Apply apps
    for app in app_paths:
        logger.info(f"📥 Applying apps from: {app}")
        os.system(f"kubectl apply -f {app}")

    register_entry(cluster_name, file_path)
    return {"status": "ok", "cluster": cluster_name, "apps": len(app_paths)}
