
import subprocess
import logging
from pathlib import Path
import yaml
from kubernetes import config, client
from kubernetes.dynamic import DynamicClient



def run_command(
    cmd: list[str],
    *,
    check: bool = True,
    capture_output: bool = False,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess:
    cmd_str = ' '.join(cmd)
    logging.debug(f"💻 Running: {cmd_str}")
    try:
        result = subprocess.run(
            cmd,
            check=check,
            text=True,
            cwd=cwd,
            stdout=subprocess.PIPE if capture_output else None,
            stderr=subprocess.PIPE if capture_output else None,
        )
        if capture_output:
            logging.debug(f"🟢 Output:\n{result.stdout}")
        return result
    except subprocess.CalledProcessError as e:
        msg = f"❌ Command failed: {cmd_str} (exit code: {e.returncode})"
        if capture_output:
            msg += f"\nStdout:\n{e.stdout}\nStderr:\n{e.stderr}"
        logging.error(msg)
        raise

def apply_kustomize(path: Path):
    if not path.is_dir() or not (path / "kustomization.yaml").exists():
        raise FileNotFoundError(f"Invalid Kustomize directory: {path}")
    logging.info(f"📦 Applying Kustomize: {path}")
    run_command(["kubectl", "apply", "-k", str(path)])



def install_helm_chart(
    release_name: str,
    repo_name: str,
    repo_url: str,
    chart_name: str,
    namespace: str,
    values_file: Path | None = None,
    timeout: str = "300s"
):
    if values_file and not values_file.exists():
        raise FileNotFoundError(f"Missing Helm values file: {values_file}")

    logging.info(f"🚀 Installing Helm release '{release_name}' in namespace '{namespace}'")

    run_command(["helm", "repo", "add", repo_name, repo_url])
    run_command(["helm", "repo", "update"])

    cmd = [
        "helm", "upgrade", "--install", release_name, f"{repo_name}/{chart_name}",
        "--namespace", namespace, "--create-namespace",
        "--wait", "--timeout", timeout
    ]
    if values_file:
        cmd += ["--values", str(values_file)]

    run_command(cmd)
    logging.info(f"✅ Helm release '{release_name}' installed successfully.")

def apply_manifest(path: Path):
    config.load_kube_config()
    dyn_client = DynamicClient(client.ApiClient())

    with open(path) as f:
        docs = list(yaml.safe_load_all(f))

    for doc in docs:
        if not doc or not doc.get("kind") or not doc.get("apiVersion"):
            continue
        kind = doc["kind"]
        api_version = doc["apiVersion"]
        namespace = doc.get("metadata", {}).get("namespace", "default")
        resource = dyn_client.resources.get(api_version=api_version, kind=kind)

        try:
            logging.info(f"📄 Applying {kind} to namespace {namespace}")
            resource.create(body=doc, namespace=namespace)
        except client.exceptions.ApiException as e:
            if e.status == 409:
                logging.info(f"↪️ {kind} exists. Patching...")
                resource.patch(body=doc, namespace=namespace)
            else:
                raise




def bootstrap_gitops_stack(
    env: str,
    install_flux: bool = False,
    install_fleet: bool = False,
    skip_argocd: bool = False
) -> None:
    """
    Bootstraps GitOps stack for the given environment.
    Always applies CoreDNS first.
    Then installs:
      - FluxCD (and applies kustomization-system.yaml)
      - Fleet (and applies system-gitrepo.yaml)
      - or ArgoCD (and applies root-app.yaml unless skipped)
    """
    logging.info(f"🔧 Starting GitOps bootstrap for environment: {env}")
    config.load_kube_config()

    try:
        apply_kustomize(Path("apps/system/base/coredns"))
    except Exception as e:
        logging.error(f"❌ Failed to bootstrap CoreDNS: {e}")
        raise

    try:
        if install_flux:
            install_flux()
            apply_manifest(Path("apps/gitops/flux/kustomization-system.yaml"))
            logging.info("✅ Flux bootstrapped.")
            return

        if install_fleet:
            install_fleet()
            apply_manifest(Path("apps/gitops/fleet/system-gitrepo.yaml"))
            logging.info("✅ Fleet bootstrapped.")
            return

        if skip_argocd:
            logging.info("⚠️ Skipping ArgoCD installation as requested.")
            return

        install_helm_chart(
            release_name="argocd",
            repo_name="argo",
            repo_url="https://argoproj.github.io/argo-helm",
            chart_name="argo-cd",
            namespace="argocd",
            values_file=Path("apps/system/base/argocd/values.yaml")
        )
    except Exception as e:
        logging.error(f"❌ GitOps install failed: {e}")
        raise

    root_app = Path(f"apps/gitops/argocd/{env}/root-app.yaml")
    if not root_app.exists():
        raise FileNotFoundError(f"❌ root-app.yaml not found: {root_app}")

    try:
        logging.info(f"📂 Applying ArgoCD root app for '{env}'")
        run_command(["kubectl", "apply", "-f", str(root_app)])
    except Exception as e:
        logging.error(f"❌ Failed to apply root-app.yaml: {e}")
        raise

    logging.info("🎉 GitOps stack bootstrapped successfully.")

def install_flux():
    logging.info("🚀 Installing FluxCD...")
    run_command([
        "helm", "upgrade", "--install", "flux2", "fluxcd-community/flux2",
        "--repo", "https://fluxcd-community.github.io/helm-charts",
        "--namespace", "flux-system", "--create-namespace",
        "--wait", "--timeout", "300s"
    ])
    logging.info("✅ FluxCD installed successfully.")


def install_fleet():
    logging.info("🚀 Installing Rancher Fleet...")
    run_command([
        "helm", "upgrade", "--install", "fleet", "fleet/fleet",
        "--repo", "https://rancher.github.io/fleet-helm-charts",
        "--namespace", "cattle-fleet-system", "--create-namespace",
        "--wait", "--timeout", "300s"
    ])
    logging.info("✅ Fleet installed successfully.")
