from kubernetes import config, client
from kubernetes.client.rest import ApiException

def get_summary(namespace="argocd"):
    config.load_kube_config()
    api = client.CustomObjectsApi()

    try:
        apps = api.list_namespaced_custom_object(
            group="argoproj.io",
            version="v1alpha1",
            namespace=namespace,
            plural="applications"
        )

        summary = {
            "total": 0,
            "synced": 0,
            "out_of_sync": 0,
            "healthy": 0,
            "degraded": 0
        }

        for app in apps.get("items", []):
            summary["total"] += 1
            sync_status = app.get("status", {}).get("sync", {}).get("status", "")
            health_status = app.get("status", {}).get("health", {}).get("status", "")
            if sync_status == "Synced":
                summary["synced"] += 1
            else:
                summary["out_of_sync"] += 1
            if health_status == "Healthy":
                summary["healthy"] += 1
            else:
                summary["degraded"] += 1

        return summary
    except ApiException as e:
        return {"status": "error", "details": e.body}
