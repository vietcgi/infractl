
import os
import time
import logging
import bcrypt
from dotenv import load_dotenv
from kubernetes import client, config
from kubernetes.client.rest import ApiException
from kubernetes.dynamic import DynamicClient
import yaml

# Safely apply a Kubernetes manifest dict using DynamicClient
# - Handles missing metadata and avoids duplicate error spam
def apply_manifest_dict_safe(doc):
    if not doc or not doc.get("kind") or not doc.get("apiVersion"):
        return

    if not doc.get("metadata"):
        doc["metadata"] = {}
    if not doc["metadata"].get("namespace"):
        doc["metadata"]["namespace"] = "argocd"

    k8s_client = client.ApiClient()
    dyn_client = DynamicClient(k8s_client)

    try:
        resource = dyn_client.resources.get(
            api_version=doc["apiVersion"],
            kind=doc["kind"]
        )
        namespace = doc["metadata"]["namespace"]
        resource.create(body=doc, namespace=namespace, _preload_content=False)
        logging.info(f"✅ Applied: {doc['kind']} {doc['metadata'].get('name')} in {namespace}")
    except ApiException as e:
        if e.status == 409 or "kubectl.kubernetes.io/last-applied-configuration" in str(e.body):
            return
        logging.error(f"❌ Failed to apply {doc['kind']}: {e}")
        raise

# Bootstrap ArgoCD apps using a local manifest
# - Applies each manifest in apps/system/bootstrap-system-apps.yaml
def bootstrap_argocd_apps(manifest_path="apps/argocd/root-app.yaml"):
    print(f"🚀 Bootstrapping ArgoCD apps from {manifest_path}...")

    if not os.path.exists(manifest_path):
        print(f"⚠️ ArgoCD bootstrap file not found: {manifest_path}")
        return

    with open(manifest_path, "r") as f:
        docs = list(yaml.safe_load_all(f))

    for doc in docs:
        try:
            apply_manifest_dict_safe(doc)
        except Exception as e:
            print(f"❌ Failed to apply ArgoCD app: {e}")
    print("✅ ArgoCD apps bootstrapped.")

# Install ArgoCD using native K8s SDK
# - Sets bcrypt password from .env
# - Creates or patches argocd-secret
# - Deletes argocd-initial-admin-secret
# - Applies official ArgoCD manifest
# - Bootstraps system apps
def install_argocd_from_addons():
    print("📦 Installing ArgoCD and setting initial admin password (bcrypt)...")

    try:
        config.load_kube_config()
        core_v1 = client.CoreV1Api()
        namespace = "argocd"
        secret_name = "argocd-secret"

        # Ensure namespace
        ns = client.V1Namespace(metadata=client.V1ObjectMeta(name=namespace))
        try:
            core_v1.create_namespace(ns)
            print(f"✅ Created namespace: {namespace}")
        except ApiException as e:
            if e.status != 409:
                raise
            print(f"ℹ️ Namespace '{namespace}' already exists.")

        # Load .env password and hash
        load_dotenv()
        password = os.getenv("ARGOCD_ADMIN_PASSWORD", "admin123")
        hashed_password = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

        # Create or patch secret
        try:
            core_v1.create_namespaced_secret(
                namespace=namespace,
                body=client.V1Secret(
                    metadata=client.V1ObjectMeta(name=secret_name),
                    type="Opaque",
                    string_data={"admin.password": hashed_password}
                )
            )
            print("✅ Created argocd-secret with bcrypt password.")
        except ApiException as e:
            if e.status == 409:
                patch_body = {"stringData": {"admin.password": hashed_password}}
                core_v1.patch_namespaced_secret(secret_name, namespace, patch_body)
                print("✅ Patched existing argocd-secret with bcrypt password.")
            else:
                raise

        # Delete auto-generated secret
        try:
            core_v1.delete_namespaced_secret("argocd-initial-admin-secret", namespace)
            print("🧼 Deleted argocd-initial-admin-secret.")
        except ApiException as e:
            if e.status != 404:
                raise
            print("ℹ️ argocd-initial-admin-secret not present.")

        # Install Argo CD
        import subprocess
        subprocess.run([
            "kubectl", "apply", "-n", namespace,
            "-f", "https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml"
        ], check=True)

        print("✅ ArgoCD installed and configured with bcrypt password.")
        bootstrap_argocd_apps()

    except Exception as e:
        print(f"❌ Failed to install ArgoCD: {e}")

# --- GitOps tools below ---

def install_fleet():
    print("📦 Installing Fleet GitOps...")
    try:
        config.load_kube_config()
        v1 = client.CoreV1Api()
        ns = "cattle-fleet-system"
        ns_obj = client.V1Namespace(metadata=client.V1ObjectMeta(name=ns))
        try:
            v1.create_namespace(ns_obj)
            print(f"✅ Created namespace: {ns}")
        except ApiException as e:
            if e.status != 409:
                raise
            print(f"ℹ️ Namespace '{ns}' already exists.")

        import subprocess
        subprocess.run("helm repo add fleet https://rancher.github.io/fleet-helm-charts", shell=True, check=False)
        subprocess.run("helm repo update", shell=True, check=True)
        subprocess.run("helm upgrade --install fleet fleet/fleet -n cattle-fleet-system --create-namespace", shell=True, check=True)
        print("✅ Fleet installation completed.")
    except Exception as e:
        print(f"❌ Failed to install Fleet: {e}")

def install_flux():
    print("📦 Installing FluxCD GitOps...")
    try:
        config.load_kube_config()
        v1 = client.CoreV1Api()
        ns = "flux-system"
        ns_obj = client.V1Namespace(metadata=client.V1ObjectMeta(name=ns))
        try:
            v1.create_namespace(ns_obj)
            print(f"✅ Created namespace: {ns}")
        except ApiException as e:
            if e.status != 409:
                raise
            print(f"ℹ️ Namespace '{ns}' already exists.")

        import subprocess
        subprocess.run("helm repo add fluxcd https://fluxcd-community.github.io/helm-charts", shell=True, check=False)
        subprocess.run("helm repo update", shell=True, check=True)
        subprocess.run("helm upgrade --install flux fluxcd/flux2 -n flux-system --create-namespace", shell=True, check=True)
        print("✅ FluxCD installation completed.")
    except Exception as e:
        print(f"❌ Failed to install FluxCD: {e}")