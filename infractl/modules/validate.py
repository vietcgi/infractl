import subprocess

def run(file):
    print(f"🧪 Validating cluster file: {file}")
    subprocess.run(f"python3 scripts/validate-cluster.py {file}", shell=True, check=True)
