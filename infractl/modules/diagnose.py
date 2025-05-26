import subprocess

def run(component):
    if component == "argocd":
        print("🔍 Running ArgoCD diagnosis...")
        subprocess.run("bash scripts/argocd-doctor.sh", shell=True, check=True)
    else:
        print(f"❌ Diagnose: Unsupported component '{component}'")
