import os
import subprocess
import logging
import yaml

from kubernetes import client, config
from kubernetes.client.rest import ApiException
from kubernetes.dynamic import DynamicClient

logging.basicConfig(level=logging.INFO)

def apply_manifest_dict_safe(doc: dict, default_namespace: str = "argocd") -> None:
    """
    Safely apply a Kubernetes manifest using the dynamic client.
    Falls back to default namespace if not specified in the manifest.
    """
    if not doc or not doc.get("kind") or not doc.get("apiVersion"):
        return

    if not doc.get("metadata"):
        doc["metadata"] = {}
    if not doc["metadata"].get("namespace"):
        doc["metadata"]["namespace"] = default_namespace

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
        if e.status == 409 or "already exists" in str(e.body):
            logging.info(f"ℹ️ Skipped existing: {doc['kind']} {doc['metadata'].get('name')}")
            return
        logging.error(f"❌ Failed to apply {doc['kind']}: {e}")
        raise

def bootstrap_argocd_apps(manifest_path: str = "apps/argocd/root-app.yaml") -> None:
    """
    Bootstrap ArgoCD applications by applying a root AppSet or manifest.
    """
    if not os.path.exists(manifest_path):
        logging.warning(f"⚠️ ArgoCD manifest not found at: {manifest_path}")
        return

    with open(manifest_path, "r") as f:
        docs = list(yaml.safe_load_all(f))

    for doc in docs:
        try:
            apply_manifest_dict_safe(doc)
        except Exception as e:
            logging.error(f"❌ Failed to apply manifest: {e}")
    logging.info("✅ ArgoCD apps bootstrapped.")

def bootstrap_coredns(values_path: str = "apps/system/base/coredns/values.yaml") -> None:
    """
    Install CoreDNS using Helm with the provided values file.
    """
    if not os.path.exists(values_path):
        logging.warning(f"⚠️ CoreDNS values.yaml not found at {values_path}")
        return

    helm_cmd = [
        "helm", "upgrade", "--install", "coredns", "coredns/coredns",
        "--namespace", "kube-system",
        "-f", values_path,
        "--create-namespace"
    ]
    logging.info("🚀 Installing CoreDNS via Helm...")
    try:
        subprocess.run(helm_cmd, check=True)
        logging.info("✅ CoreDNS installed successfully.")
    except subprocess.CalledProcessError as e:
        logging.error(f"❌ CoreDNS installation failed: {e}")

def bootstrap_gitops_stack() -> None:
    """
    Bootstrap the GitOps foundation:
    - Install CoreDNS (manual bootstrap)
    - Install ArgoCD via Helm
    - Apply ArgoCD root app manifest
    """
    logging.info("📦 Bootstrapping GitOps stack...")

    try:
        config.load_kube_config()
    except Exception:
        config.load_incluster_config()

    core_v1 = client.CoreV1Api()
    namespace = "argocd"

    # Ensure ArgoCD namespace exists
    ns = client.V1Namespace(metadata=client.V1ObjectMeta(name=namespace))
    try:
        core_v1.create_namespace(ns)
        logging.info(f"✅ Created namespace: {namespace}")
    except ApiException as e:
        if e.status != 409:
            raise
        logging.info(f"ℹ️ Namespace '{namespace}' already exists.")

    # Step 1: Bootstrap CoreDNS first (needed for GitOps DNS resolution)
    bootstrap_coredns()

    # Step 2: Install ArgoCD via Helm
    logging.info("🚀 Installing ArgoCD via Helm...")
    subprocess.run(["helm", "repo", "add", "argo", "https://argoproj.github.io/argo-helm"], check=True)
    subprocess.run(["helm", "repo", "update"], check=True)
    subprocess.run([
        "helm", "upgrade", "--install", "argocd", "argo/argo-cd",
        "--namespace", namespace, "--create-namespace",
        "-f", "apps/system/base/argocd/values.yaml"
    ], check=True)
    logging.info("✅ ArgoCD installed successfully.")

    # Step 3: Apply ArgoCD root AppSet
    bootstrap_argocd_apps()

    logging.info("🎉 GitOps bootstrap complete.")


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