import subprocess
import logging
from pathlib import Path
import yaml
from kubernetes import config, client
from kubernetes.dynamic import DynamicClient
from typing import Optional, Dict, Any, List, Union, Tuple


def find_values_file(component: str, env: str, cluster: Optional[str] = None) -> Path:
    """
    Find the most specific values file for a component based on environment and cluster.
    
    Search order:
    1. Cluster-specific values: system/overlays/{env}/{cluster}/{component}/values.yaml
    2. Environment values: system/overlays/{env}/{component}/values.yaml
    3. Base values: system/base/{component}/values.yaml
    
    Args:
        component: The component name (e.g., 'argocd')
        env: The environment (e.g., 'prod', 'dev')
        cluster: Optional cluster name (e.g., 'dc11a')
        
    Returns:
        Path to the most specific values file found
        
    Raises:
        FileNotFoundError: If no values file is found
    """
    # Try cluster-specific values first (for any environment)
    if cluster:
        cluster_values = Path(f"apps/system/overlays/{env}/{cluster}/{component}/values.yaml")
        if cluster_values.exists():
            return cluster_values
    
    # Try environment-specific values
    env_values = Path(f"apps/system/overlays/{env}/{component}/values.yaml")
    if env_values.exists():
        return env_values
    
    # Fall back to base values
    base_values = Path(f"apps/system/base/{component}/values.yaml")
    if base_values.exists():
        return base_values
    
    raise FileNotFoundError(
        f"No values file found for {component} in env={env}, cluster={cluster}. "
        f"Tried: {[str(p) for p in [cluster_values, env_values, base_values] if 'p' in locals()]}"
    )


def merge_values(*values_files: Path) -> Dict[str, Any]:
    """Merge multiple YAML values files, with later files taking precedence."""
    result = {}
    for file in values_files:
        if file.exists():
            with open(file) as f:
                file_values = yaml.safe_load(f) or {}
                deep_merge(result, file_values)
    return result


def deep_merge(base: Dict[str, Any], update: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively merge two dictionaries, with update taking precedence."""
    for key, value in update.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            base[key] = deep_merge(base[key], value)
        else:
            base[key] = value
    return base


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




def create_sealed_secrets_key():
    """Create Sealed Secrets TLS secret in kube-system namespace."""
    key_dir = Path(".sealedsecrets-keypair")
    if not key_dir.exists():
        logging.warning("⚠️  Sealed Secrets key directory not found, skipping key creation")
        return
        
    cert_path = key_dir / "tls.crt"
    key_path = key_dir / "tls.key"
    
    if not cert_path.exists() or not key_path.exists():
        # Try alternative filenames
        cert_path = key_dir / "controller.crt"
        key_path = key_dir / "controller.key"
        if not cert_path.exists() or not key_path.exists():
            logging.warning(f"⚠️  Sealed Secrets key files not found in {key_dir}, skipping key creation")
            return
    
    logging.info("🔑 Creating Sealed Secrets TLS secret in kube-system namespace")
    
    # Check if secret already exists
    result = run_command(
        ["kubectl", "-n", "kube-system", "get", "secret", "sealed-secrets-key"],
        check=False,
        capture_output=True
    )
    
    if result.returncode == 0:
        logging.info("🔄 Updating existing Sealed Secrets secret")
        run_command([
            "kubectl", "-n", "kube-system", "delete", "secret", "sealed-secrets-key"
        ])
    
    # Create the secret
    run_command([
        "kubectl", "-n", "kube-system", "create", "secret", "tls", "sealed-secrets-key",
        f"--cert={cert_path}",
        f"--key={key_path}"
    ])
    logging.info("✅ Sealed Secrets TLS secret created successfully")


def bootstrap_gitops_stack(
    env: str,
    install_flux: bool = False,
    install_fleet: bool = False,
    skip_argocd: bool = False,
    kubeconfig_path: str = None,
    cluster: str = None
) -> None:
    """
    Bootstraps GitOps stack for the given environment.
    Always applies CoreDNS first, then creates Sealed Secrets key if available.
    Then installs:
      - FluxCD (and applies kustomization-system.yaml)
      - Fleet (and applies system-gitrepo.yaml)
      - or ArgoCD (and applies root-app.yaml unless skipped)
    
    Args:
        env: Environment name (e.g., 'dev', 'prod')
        install_flux: Whether to install FluxCD
        install_fleet: Whether to install Fleet
        skip_argocd: Whether to skip ArgoCD installation
        kubeconfig_path: Path to the kubeconfig file (optional)
    """
    logging.info(f"🔧 Starting GitOps bootstrap for environment: {env}")
    
    # Set KUBECONFIG environment variable if kubeconfig_path is provided
    if kubeconfig_path:
        import os
        os.environ['KUBECONFIG'] = kubeconfig_path
    
    # Try to load kubeconfig, but don't fail if it doesn't exist yet
    try:
        config.load_kube_config()
    except config.config_exception.ConfigException as e:
        if "No configuration found" in str(e):
            logging.warning("⚠️  No kubeconfig found. This is normal for a new cluster. "
                         "The kubeconfig will be created during cluster provisioning.")
            return
        raise

    try:
        # 1. Install CoreDNS
        logging.info("🌐 Installing CoreDNS")
        apply_kustomize(Path("apps/system/base/coredns"))
        
        # 2. Create Sealed Secrets TLS secret if key files exist
        try:
            create_sealed_secrets_key()
        except Exception as e:
            logging.warning(f"⚠️  Failed to create Sealed Secrets key: {e}")
            logging.warning("This is non-fatal but may affect Sealed Secrets functionality")
            
    except Exception as e:
        logging.error(f"❌ Failed during initial bootstrap: {e}")
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

        # Install ArgoCD with appropriate values file
        logging.info("🚀 Installing ArgoCD...")
        
        try:
            # Find the most specific values file for this environment and cluster
            values_file = find_values_file("argocd", env, cluster)
            logging.info(f"📋 Using values file: {values_file}")
            
            install_helm_chart(
                release_name="argocd",
                repo_name="argo",
                repo_url="https://argoproj.github.io/argo-helm",
                chart_name="argo-cd",
                namespace="argocd",
                values_file=values_file
            )
            logging.info("✅ ArgoCD installed successfully.")
            
        except FileNotFoundError as e:
            logging.error(f"❌ Failed to find values file for ArgoCD: {e}")
            logging.error("Using default values, but this may not be what you want.")
            
            # Fall back to default installation without values file
            install_helm_chart(
                release_name="argocd",
                repo_name="argo",
                repo_url="https://argoproj.github.io/argo-helm",
                chart_name="argo-cd",
                namespace="argocd"
            )
            logging.info("✅ ArgoCD installed with default values.")

        # Wait for ArgoCD to be ready
        logging.info("⏳ Waiting for ArgoCD to be ready...")
        run_command([
            "kubectl", "wait", "--for=condition=available", "deployment/argocd-server",
            "-n", "argocd", "--timeout=300s"
        ])

        # Apply the ArgoCD Application CRD for self-management
        logging.info(f"🔄 Setting up ArgoCD self-management for environment: {env}...")
        
        # First, apply the root application that points to the correct environment and cluster
        root_app_path = Path(f"apps/gitops/argocd/{env}")
        
        # If we have a cluster name, use the cluster-specific root app if it exists
        if cluster:
            cluster_root_app = root_app_path / cluster / "root-app.yaml"
            if cluster_root_app.exists():
                root_app_path = cluster_root_app
                logging.info(f"🔧 Found cluster-specific root app at: {root_app_path}")
            else:
                # Fall back to environment root app
                root_app_path = root_app_path / "root-app.yaml"
                logging.info(f"ℹ️  Using environment root app at: {root_app_path}")
        else:
            root_app_path = root_app_path / "root-app.yaml"
        
        if not root_app_path.exists():
            raise FileNotFoundError(
                f"❌ Root application not found. "
                f"Expected file: {root_app_path}"
            )
        
        # Apply the root application
        logging.info(f"🔧 Applying root application from: {root_app_path}")
        run_command(["kubectl", "apply", "-f", str(root_app_path)])
        logging.info("✅ Root application configured.")
        
        # For backward compatibility, also apply the Kustomize overlay if it exists
        overlay_path = Path(f"apps/system/overlays/{env}")
        if cluster and env == 'prod':
            cluster_overlay = overlay_path / cluster / "argocd"
            if cluster_overlay.exists():
                overlay_path = cluster_overlay
                logging.info(f"🔧 Found cluster-specific overlay at: {overlay_path}")
            else:
                overlay_path = overlay_path / "argocd"
        else:
            overlay_path = overlay_path / "argocd"
        
        if overlay_path.exists():
            logging.info(f"🔧 Applying Kustomize overlay from: {overlay_path}")
            run_command(["kubectl", "apply", "-k", str(overlay_path)])
            logging.info("✅ ArgoCD overlay configuration applied.")
        else:
            logging.warning(f"⚠️  No Kustomize overlay found at: {overlay_path}")
            
        logging.info("✅ ArgoCD self-management configured.")

        # Verify the Application is created and synced
        try:
            # Wait for Application CRD to be established
            run_command([
                "kubectl", "wait", "--for=condition=Established",
                "crd/applications.argoproj.io", "--timeout=60s"
            ])
            logging.info("✅ ArgoCD Application CRD is ready.")
            
            # Wait for the Application to be healthy
            run_command([
                "kubectl", "wait", "application/argocd",
                "-n", "argocd",
                "--for=condition=Healthy",
                "--timeout=300s"
            ])
            logging.info("✅ ArgoCD Application is healthy.")
            
        except subprocess.CalledProcessError as e:
            logging.warning(f"⚠️  ArgoCD Application verification warning: {e}")
            logging.info("This might be expected if this is the first sync. ArgoCD will reconcile the state.")

    except Exception as e:
        logging.error(f"❌ GitOps bootstrap failed: {e}")
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


def create_sealed_secrets_key():
    """
    Create or update the Sealed Secrets TLS secret in the kube-system namespace.
    
    Looks for key files in .sealedsecrets-keypair/ with either:
    - tls.crt and tls.key, or
    - controller.crt and controller.key
    """
    key_dir = Path(".sealedsecrets-keypair")
    if not key_dir.exists():
        logging.warning("⚠️  Sealed Secrets key directory not found at .sealedsecrets-keypair/")
        return False
    
    # Try both filename patterns
    cert_path = key_dir / "tls.crt"
    key_path = key_dir / "tls.key"
    
    if not cert_path.exists() or not key_path.exists():
        cert_path = key_dir / "controller.crt"
        key_path = key_dir / "controller.key"
        if not cert_path.exists() or not key_path.exists():
            logging.warning("⚠️  Could not find Sealed Secrets key files (tried .crt/.key and controller.crt/controller.key)")
            return False
    
    logging.info(f"🔑 Found Sealed Secrets key files at {key_dir}")
    
    # Check if secret already exists
    result = run_command(
        ["kubectl", "-n", "kube-system", "get", "secret", "sealed-secrets-key"],
        check=False,
        capture_output=True
    )
    
    if result.returncode == 0:
        logging.info("🔄 Updating existing Sealed Secrets secret")
        run_command([
            "kubectl", "-n", "kube-system", "delete", "secret", "sealed-secrets-key"
        ], check=False)
    
    # Create the secret
    try:
        run_command([
            "kubectl", "-n", "kube-system", "create", "secret", "tls", "sealed-secrets-key",
            f"--cert={cert_path}",
            f"--key={key_path}"
        ])
        logging.info("✅ Sealed Secrets TLS secret created/updated in kube-system namespace")
        return True
    except Exception as e:
        logging.error(f"❌ Failed to create Sealed Secrets secret: {e}")
        return False
