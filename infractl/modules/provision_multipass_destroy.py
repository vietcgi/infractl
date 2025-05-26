import subprocess
import typer
import os

def destroy_instances(name: str, generate_inventory: bool = False):
    result = subprocess.run(["multipass", "list"], capture_output=True, text=True)
    instances = [line.split()[0] for line in result.stdout.splitlines()[1:] if name in line]

    for instance in instances:
        print(f"🗑️ Deleting {instance}")
        subprocess.run(["multipass", "delete", instance], check=True)

    subprocess.run(["multipass", "purge"], check=True)
    print("✅ All matching instances deleted.")

    if generate_inventory:
        hosts_path = f"ansible/hosts-{name}.ini"
        if os.path.exists(hosts_path):
            os.remove(hosts_path)
            print(f"🧹 Removed inventory: {hosts_path}")
