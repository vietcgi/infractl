from kubernetes import config, client
from kubernetes.client.rest import ApiException

def sync_all_labeled(namespace="argocd", label_selector="auto-sync=on"):
    config.load_kube_config()
    api = client.CustomObjectsApi()

    try:
        apps = api.list_namespaced_custom_object(
            group="argoproj.io",
            version="v1alpha1",
            namespace=namespace,
            plural="applications",
            label_selector=label_selector
        )

        results = []
        for app in apps.get("items", []):
            name = app["metadata"]["name"]
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
            results.append({"app": name, "status": "sync triggered"})

        return {"synced_apps": results, "count": len(results)}

    except ApiException as e:
        return {"status": "error", "details": e.body}
