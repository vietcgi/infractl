from kubernetes import config, client
from kubernetes.client.rest import ApiException

def trigger_sync(app_name: str, namespace="argocd"):
    config.load_kube_config()
    api = client.CustomObjectsApi()

    try:
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
            name=app_name,
            body=patch
        )
        return {"status": "sync triggered", "app": app_name}
    except ApiException as e:
        return {"status": "error", "details": e.body}
