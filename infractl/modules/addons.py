import os
import subprocess
import logging
import yaml

from kubernetes import client, config
from kubernetes.client.rest import ApiException
from kubernetes.dynamic import DynamicClient

logging.basicConfig(level=logging.INFO)

def apply_manifest_dict_safe(doc: dict, default_namespace: str = "argocd") -> None:
    if not doc or not doc.get("kind") or not doc.get("apiVersion"):
        return

    if not doc.get("metadata"):
        doc["metadata"] = {}
    if not doc["metadata"].get("namespace"):
        doc["metadata"]["namespace"] = default_namespace

    k8s_client = client.ApiClient()
    dyn_client = DynamicClient(k8s_client)

    try:
        resource = dyn_client.resources.get(api_version=doc["apiVersion"], kind=doc["kind"])
        namespace = doc["metadata"]["namespace"]
        resource.create(body=doc, namespace=namespace, _preload_content=False)
        logging.info(f"✅ Applied: {doc['kind']} {doc['metadata'].get('name')} in {namespace}")
    except ApiException as e:
        if e.status == 409 or "already exists" in str(e.body):
            logging.info(f"ℹ️ Skipped existing: {doc['kind']} {doc['metadata'].get('name')}")
        else:
            logging.error(f"❌ Failed to apply {doc['kind']}: {e}")
            raise

def bootstrap_argocd_apps(manifest_path: str = "apps/argocd/root-app.yaml") -> None:
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
    if not os.path.exists(values_path):
        logging.warning(f"⚠️ CoreDNS values.yaml not found at {values_path}")
        return

    helm_cmd = [
        "helm", "upgrade", "--install", "coredns", "coredns/coredns",
        "--namespace", "kube-system", "-f", values_path,
        "--create-namespace", "--wait", "--timeout", "120s"
    ]
    logging.info("🚀 Installing CoreDNS via Helm...")
    try:
        subprocess.run(helm_cmd, check=True)
        logging.info("✅ CoreDNS installed successfully.")
    except subprocess.CalledProcessError as e:
        logging.error(f"❌ CoreDNS installation failed: {e}")

def create_namespace_if_missing(namespace: str):
    core_v1 = client.CoreV1Api()
    ns = client.V1Namespace(metadata=client.V1ObjectMeta(name=namespace))
    try:
        core_v1.create_namespace(ns)
        logging.info(f"✅ Created namespace: {namespace}")
    except ApiException as e:
        if e.status != 409:
            raise
        logging.info(f"ℹ️ Namespace '{namespace}' already exists.")

def bootstrap_gitops_stack(kubeconfig_path: str = "~/.kube/config") -> None:
    logging.info("📦 Bootstrapping GitOps stack...")
    kubeconfig_path = os.path.expanduser(kubeconfig_path)

    if not os.path.exists(kubeconfig_path):
        raise FileNotFoundError(f"❌ Kubeconfig file not found: {kubeconfig_path}")

    config.load_kube_config(config_file=kubeconfig_path)

    create_namespace_if_missing("argocd")
    bootstrap_coredns()

    logging.info("🚀 Installing ArgoCD via Helm...")
    subprocess.run(["helm", "repo", "add", "argo", "https://argoproj.github.io/argo-helm"], check=True)
    subprocess.run(["helm", "repo", "update"], check=True)
    subprocess.run([
        "helm", "upgrade", "--install", "argocd", "argo/argo-cd",
        "--namespace", "argocd", "--create-namespace",
        "-f", "apps/system/base/argocd/values.yaml",
        "--wait", "--timeout", "300s"
    ], check=True)
    logging.info("✅ ArgoCD installed successfully.")

    bootstrap_argocd_apps()
    logging.info("🎉 GitOps bootstrap complete.")

def install_helm_chart(name, repo, chart, namespace):
    subprocess.run(["helm", "repo", "add", name, repo], check=True)
    subprocess.run(["helm", "repo", "update"], check=True)
    subprocess.run([
        "helm", "upgrade", "--install", name, chart,
        "-n", namespace, "--create-namespace", "--wait"
    ], check=True)

def install_fleet():
    logging.info("📦 Installing Fleet GitOps...")
    config.load_kube_config()
    create_namespace_if_missing("cattle-fleet-system")
    install_helm_chart("fleet", "https://rancher.github.io/fleet-helm-charts", "fleet/fleet", "cattle-fleet-system")
    logging.info("✅ Fleet installation completed.")

def install_flux():
    logging.info("📦 Installing FluxCD GitOps...")
    config.load_kube_config()
    create_namespace_if_missing("flux-system")
    install_helm_chart("fluxcd", "https://fluxcd-community.github.io/helm-charts", "fluxcd/flux2", "flux-system")
    logging.info("✅ FluxCD installation completed.")