#!/bin/bash
set -e

# Create ClusterRole for metrics-server
kubectl apply -f - <<EOF
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: metrics-server-auth-delegator
  labels:
    app.kubernetes.io/name: metrics-server
    app.kubernetes.io/part-of: kube-system
rules:
- apiGroups: ["authorization.k8s.io"]
  resources: ["subjectaccessreviews"]
  verbs: ["create"]
- apiGroups: [""]
  resources: ["nodes/metrics"]
  verbs: ["get"]
- nonResourceURLs: ["/metrics"]
  verbs: ["get"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: metrics-server-auth-delegator
  labels:
    app.kubernetes.io/name: metrics-server
    app.kubernetes.io/part-of: kube-system
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: metrics-server-auth-delegator
subjects:
- kind: ServiceAccount
  name: metrics-server
  namespace: metrics-server
- kind: ServiceAccount
  name: metrics-server-dc11a
  namespace: metrics-server
---
# Additional RBAC for system:metrics-server ClusterRole
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: system:metrics-server
  labels:
    app.kubernetes.io/name: metrics-server
    app.kubernetes.io/part-of: kube-system
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: system:metrics-server
subjects:
- kind: ServiceAccount
  name: metrics-server
  namespace: metrics-server
- kind: ServiceAccount
  name: metrics-server-dc11a
  namespace: metrics-server
EOF

# Restart metrics-server deployments to pick up the new permissions
kubectl rollout restart deployment -n metrics-server metrics-server
kubectl rollout restart deployment -n metrics-server metrics-server-dc11a

echo "RBAC permissions applied and metrics-server deployments restarted. Checking status..."

# Check the status of the metrics-server APIs
echo -e "\nAPI Service status:"
kubectl get apiservice v1beta1.metrics.k8s.io -o yaml | grep -A 5 'status:'

# Check metrics-server pod status
echo -e "\nMetrics-server pod status:"
kubectl get pods -n metrics-server

# Check metrics-server service endpoints
echo -e "\nMetrics-server service endpoints:"
kubectl get endpoints -n metrics-server

# Check if metrics API is available
echo -e "\nChecking if metrics API is available:"
kubectl get --raw /apis/metrics.k8s.io/v1beta1/nodes 2>/dev/null || echo "Metrics API not yet available"
