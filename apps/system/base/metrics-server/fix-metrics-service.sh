#!/bin/bash
set -e

# Update the metrics-server service to match pod labels
kubectl apply -f - <<EOF
apiVersion: v1
kind: Service
metadata:
  name: metrics-server
  namespace: metrics-server
  labels:
    app.kubernetes.io/instance: metrics-server-prod
    app.kubernetes.io/name: metrics-server
    app.kubernetes.io/part-of: kube-system
spec:
  ports:
  - name: https
    port: 443
    protocol: TCP
    targetPort: 443
  selector:
    k8s-app: metrics-server
  type: ClusterIP
EOF

# Restart metrics-server deployments to ensure they pick up the new service
kubectl rollout restart deployment -n metrics-server metrics-server
kubectl rollout restart deployment -n metrics-server metrics-server-dc11a

echo "Metrics-server service updated and deployments restarted. Checking status..."

# Check service endpoints
echo -e "\nMetrics-server service endpoints:"
kubectl get endpoints -n metrics-server

# Check if metrics API is available
echo -e "\nChecking if metrics API is available:"
kubectl get --raw /apis/metrics.k8s.io/v1beta1/nodes 2>/dev/null && echo "Metrics API is available!" || echo "Metrics API not yet available"
