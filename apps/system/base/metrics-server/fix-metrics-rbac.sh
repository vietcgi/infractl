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
EOF

# Create ClusterRoleBinding for metrics-server
kubectl apply -f - <<EOF
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
EOF

# Restart metrics-server deployment to pick up the new permissions
kubectl rollout restart deployment -n metrics-server metrics-server

echo "RBAC permissions applied and metrics-server restarted. Checking status..."

# Check the status of the metrics-server
kubectl get apiservice v1beta1.metrics.k8s.io -o yaml | grep -A 5 'status:'

# Check metrics-server pod logs
echo -e "\nMetrics-server pod status:"
kubectl get pods -n metrics-server

echo -e "\nMetrics-server logs (last 10 lines):"
kubectl logs -n metrics-server deployment/metrics-server --tail=10

echo -e "\nChecking metrics-server service endpoints:"
kubectl get endpoints -n metrics-server

echo -e "\nChecking if metrics-server is available:"
kubectl get --raw /apis/metrics.k8s.io/v1beta1/nodes | head -n 20
