#!/bin/bash
set -e

# Create ClusterRole for metrics-server to access extension-apiserver-authentication
kubectl apply -f - <<EOF
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: system:metrics-server:auth-reader
  labels:
    app.kubernetes.io/name: metrics-server
    app.kubernetes.io/part-of: kube-system
rules:
- apiGroups: [""]
  resources: ["configmaps"]
  resourceNames: ["extension-apiserver-authentication"]
  verbs: ["get"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: metrics-server:system:auth-delegator
  labels:
    app.kubernetes.io/name: metrics-server
    app.kubernetes.io/part-of: kube-system
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: system:auth-delegator
subjects:
- kind: ServiceAccount
  name: metrics-server-dc11a
  namespace: metrics-server
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: metrics-server-auth-reader
  namespace: kube-system
  labels:
    app.kubernetes.io/name: metrics-server
    app.kubernetes.io/part-of: kube-system
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: extension-apiserver-authentication-reader
subjects:
- kind: ServiceAccount
  name: metrics-server-dc11a
  namespace: metrics-server
EOF

# Restart metrics-server deployment to pick up the new permissions
kubectl rollout restart deployment -n metrics-server metrics-server-dc11a

echo "RBAC permissions applied and metrics-server deployment restarted. Checking status..."

# Check metrics-server pod status
echo -e "\nMetrics-server pod status:"
kubectl get pods -n metrics-server

# Check metrics-server logs
echo -e "\nMetrics-server logs (last 10 lines):"
kubectl logs -n metrics-server -l k8s-app=metrics-server --tail=10

# Check if metrics API is available
echo -e "\nChecking if metrics API is available:"
kubectl get --raw /apis/metrics.k8s.io/v1beta1/nodes 2>/dev/null && echo "Metrics API is available!" || echo "Metrics API not yet available"
