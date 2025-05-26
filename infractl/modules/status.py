from kubernetes import config, client
from kubernetes.client.rest import ApiException

def check_status(app_name: str, namespace="argocd"):
    config.load_kube_config()
    api = client.CustomObjectsApi()

    try:
        app = api.get_namespaced_custom_object(
            group="argoproj.io",
            version="v1alpha1",
            namespace=namespace,
            plural="applications",
            name=app_name
        )
        status = app.get("status", {})
        return {
            "app": app_name,
            "sync_status": status.get("sync", {}).get("status", "unknown"),
            "health_status": status.get("health", {}).get("status", "unknown"),
            "revision": status.get("sync", {}).get("revision", "unknown")
        }
    except ApiException as e:
        return {"status": "error", "details": e.body}
