import os
import yaml
from modules import provision, bootstrap, register
from modules.utils import logger
from modules.registry import register_entry

def init_cluster(file: str, clean: bool = False, check: bool = True):
    if not os.path.exists(file):
        raise FileNotFoundError(f"Cluster config file not found: {file}")

    with open(file, "r") as f:
        cluster_config = yaml.safe_load(f)

    cluster_name = cluster_config.get("name")
    purpose = cluster_config.get("purpose", "unspecified")
    cluster_type = cluster_config.get("type", "unspecified")
    tags = cluster_config.get("tags", {})

    logger.info(f"🌎 Purpose: {purpose}")
    logger.info(f"🏗️ Type: {cluster_type}")
    if tags:
        logger.info(f"🔖 Tags: {tags}")

    inventory = cluster_config.get("inventory")
    kubeconfig = cluster_config.get("kubeconfig")
    apps = cluster_config.get("apps", [])

    logger.info(f"🧭 Initializing cluster: {cluster_name}")

    # Preflight check
    if check:
        logger.info("🔍 Running preflight checks...")
        if kubeconfig and not os.path.exists(kubeconfig):
            raise FileNotFoundError(f"Kubeconfig not found: {kubeconfig}")
        if inventory and not os.path.exists(inventory):
            raise FileNotFoundError(f"Inventory not found: {inventory}")
        for app_path in apps:
            if not os.path.exists(app_path):
                raise FileNotFoundError(f"App manifest not found: {app_path}")
        logger.info("✅ Preflight passed")

    # Provision
    if inventory:
        logger.info("🛠 Provisioning infrastructure...")
        provision.run(inventory=inventory)

    # Set kubeconfig
    if kubeconfig:
        os.environ["KUBECONFIG"] = kubeconfig
        logger.info(f"🔐 KUBECONFIG set to {kubeconfig}")

    # Install ArgoCD
    logger.info("🚀 Installing ArgoCD...")
    bootstrap.run(cluster_yaml="placeholder", clean=clean)

    # Apply apps
    for app_path in apps:
        logger.info(f"📥 Applying: {app_path}")
        os.system(f"kubectl apply -f {app_path}")

    # Register cluster
    register_entry(cluster_name, file, purpose=purpose, cluster_type=cluster_type, tags=tags)

    return {"status": "ok", "cluster": cluster_name, "apps_applied": len(apps)}
