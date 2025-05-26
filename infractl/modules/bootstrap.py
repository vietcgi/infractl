import subprocess
from pathlib import Path

def install_argocd(apps_bootstrap_path: str = "apps/system/bootstrap-system-apps.yaml"):
    print("📦 Installing ArgoCD...")

    try:
        subprocess.run(["kubectl", "create", "namespace", "argocd"], check=False)

        subprocess.run([
            "kubectl", "apply", "-n", "argocd",
            "-f", "https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml"
        ], check=True)

        print("⏳ Waiting for ArgoCD server rollout...")
        subprocess.run([
            "kubectl", "rollout", "status",
            "deployment/argocd-server", "-n", "argocd", "--timeout=180s"
        ], check=True)

        if Path(apps_bootstrap_path).exists():
            print(f"🚀 Applying ArgoCD bootstrap apps from {apps_bootstrap_path}")
            subprocess.run(["kubectl", "apply", "-f", apps_bootstrap_path], check=True)
        else:
            print(f"⚠️  Bootstrap file not found: {apps_bootstrap_path}")

        print("✅ ArgoCD installation complete.")
    except subprocess.CalledProcessError as e:
        print(f"❌ ArgoCD install failed: {e}")
