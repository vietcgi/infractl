from kubernetes import client, config
from kubernetes.client.rest import ApiException

def check_kube_context():
    try:
        config.load_kube_config()
        contexts, active_context = config.list_kube_config_contexts()
        return active_context['name']
    except Exception as e:
        return f"❌ Failed to load kubeconfig: {e}"

def check_crds():
    config.load_kube_config()
    api = client.ApiextensionsV1Api()
    required_crds = [
        "applications.argoproj.io",
        "applicationsets.argoproj.io",
        "sealedsecrets.bitnami.com"
    ]
    try:
        existing = [crd.metadata.name for crd in api.list_custom_resource_definition().items]
        missing = [crd for crd in required_crds if crd not in existing]
        return {"missing_crds": missing, "status": "ok" if not missing else "warning"}
    except ApiException as e:
        return {"error": str(e)}

def check_nodes():
    config.load_kube_config()
    v1 = client.CoreV1Api()
    try:
        nodes = v1.list_node().items
        return [{
            "name": node.metadata.name,
            "status": [s.type for s in node.status.conditions if s.status == "True"]
        } for node in nodes]
    except ApiException as e:
        return {"error": str(e)}

def run():
    context = check_kube_context()
    crds = check_crds()
    nodes = check_nodes()
    return {
        "kube_context": context,
        "crds": crds,
        "nodes": nodes
    }
