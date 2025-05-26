from kubernetes import config, client
from kubernetes.client.rest import ApiException

def repair_all(namespace="argocd"):
    config.load_kube_config()
    api = client.CustomObjectsApi()

    try:
        apps = api.list_namespaced_custom_object(
            group="argoproj.io",
            version="v1alpha1",
            namespace=namespace,
            plural="applications"
        )

        repaired = []
        for app in apps.get("items", []):
            name = app["metadata"]["name"]
            sync_status = app.get("status", {}).get("sync", {}).get("status", "")
            health_status = app.get("status", {}).get("health", {}).get("status", "")

            if sync_status != "Synced" or health_status != "Healthy":
                patch = {
                    "metadata": {
                        "annotations": {
                            "argocd.argoproj.io/refresh": "hard"
                        }
                    }
                }
                api.patch_namespaced_custom_object(
                    group="argoproj.io",
                    version="v1alpha1",
                    namespace=namespace,
                    plural="applications",
                    name=name,
                    body=patch
                )
                repaired.append({"app": name, "sync": sync_status, "health": health_status})

        return {"repaired_apps": repaired, "count": len(repaired)}

    except ApiException as e:
        return {"status": "error", "details": e.body}
