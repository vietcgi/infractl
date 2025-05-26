import subprocess

def run(inventory='ansible/hosts.ini', playbook='ansible/playbook.yml'):
    try:
        print(f"🚀 Running Ansible provision with inventory: {inventory}")
        cmd = ["ansible-playbook", "-i", inventory, playbook]
        subprocess.run(cmd, check=True)
        return {"status": "success", "message": "Provisioning completed"}
    except subprocess.CalledProcessError as e:
        return {"status": "error", "message": str(e)}
