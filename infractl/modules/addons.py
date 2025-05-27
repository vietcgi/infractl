import os
import shutil
import subprocess
import logging
from pathlib import Path
from typing import List
from kubernetes import client, config
from kubernetes.client.rest import ApiException
from kubernetes.dynamic import DynamicClient

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Constants
CLUSTER_ROOT = Path("clusters")
ARGOCD_SRC = Path("apps/argocd")


def run_command(cmd: List[str]):
    try:
        logging.debug(f"Running command: {' '.join(cmd)}")
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        logging.error(f"❌ Command failed: {' '.join(cmd)}\n{e}")
        raise


def apply_kustomize(path: str):
    if not os.path.isdir(path):
        logging.error(f"❌ Kustomize path not found: {path}")
        raise FileNotFoundError(f"Kustomize path not found: {path}")
    logging.info(f"📦 Applying Kustomize directory: {path}")
    run_command(["kubectl", "apply", "-k", path])


def apply_manifest(path: Path):
    if not path.exists():
        raise FileNotFoundError(f"❌ Manifest file not found: {path}")
    logging.info(f"📦 Applying manifest: {path}")
    run_command(["kubectl", "apply", "-f", str(path)])


def create_namespace_if_missing(namespace: str):
    try:
        client.CoreV1Api().create_namespace(client.V1Namespace(metadata=client.V1ObjectMeta(name=namespace)))
        logging.info(f"✅ Created namespace: {namespace}")
    except ApiException as e:
        if e.status != 409:
            raise
        logging.info(f"ℹ️ Namespace '{namespace}' already exists.")


def install_helm_chart(name: str, repo: str, chart: str, namespace: str, values_file: str = None):
    logging.info(f"🚀 Installing Helm chart: {chart} in namespace {namespace}")
    run_command(["helm", "repo", "add", name, repo])
    run_command(["helm", "repo", "update"])

    cmd = [
        "helm", "upgrade", "--install", name, chart,
        "--namespace", namespace, "--create-namespace",
        "--wait", "--timeout", "300s"
    ]

    if values_file:
        if not os.path.exists(values_file):
            raise FileNotFoundError(f"❌ Helm values file not found: {values_file}")
        cmd += ["-f", values_file]

    run_command(cmd)
    logging.info(f"✅ Helm release '{name}' installed.")


def install_flux():
    config.load_kube_config()
    create_namespace_if_missing("flux-system")
    install_helm_chart("fluxcd", "https://fluxcd-community.github.io/helm-charts", "fluxcd/flux2", "flux-system")


def install_fleet():
    config.load_kube_config()
    create_namespace_if_missing("cattle-fleet-system")
    install_helm_chart("fleet", "https://rancher.github.io/fleet-helm-charts", "fleet/fleet", "cattle-fleet-system")


def install_argocd():
    config.load_kube_config()
    create_namespace_if_missing("argocd")
    install_helm_chart(
        name="argocd",
        repo="https://argoproj.github.io/argo-helm",
        chart="argo/argo-cd",
        namespace="argocd",
        values_file="apps/system/base/argocd/values.yaml"
    )


def scaffold_cluster(env: str, region: str, name: str, platform: str = "rke2") -> Path:
    cluster_dir = CLUSTER_ROOT / platform / region / env / name
    cluster_dir.mkdir(parents=True, exist_ok=True)

    root_app_src = ARGOCD_SRC / "root-app.yaml"
    appset_src = ARGOCD_SRC / f"system-applicationset-{env}.yaml"

    if not appset_src.exists():
        raise FileNotFoundError(f"❌ Missing ApplicationSet for {env}: {appset_src}")

    shutil.copy(root_app_src, cluster_dir / "root-app.yaml")
    shutil.copy(appset_src, cluster_dir / "system-applicationset.yaml")
    logging.info(f"✅ Cluster scaffolded at: {cluster_dir}")

    return cluster_dir


def apply_network_policy():
    network_policy_path = Path("apps/system/base/argocd/networkpolicy.yaml")
    if network_policy_path.exists():
        apply_manifest(network_policy_path)
    else:
        logging.warning("⚠️ ArgoCD network policy not found.")


def bootstrap_gitops_stack(env: str, region: str, name: str, platform: str = "rke2"):
    logging.info(f"🚀 Bootstrapping GitOps stack for cluster: {name} ({platform}/{region}/{env})")
    config.load_kube_config()

    cluster_dir = scaffold_cluster(env, region, name, platform)
    apply_manifest("apps/system/base/coredns/coredns.yaml")
    install_argocd()
    apply_manifest(cluster_dir / "root-app.yaml")
    apply_network_policy()

    logging.info("🎉 GitOps bootstrap complete.")
