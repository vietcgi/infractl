# 📊 Prometheus Monitoring Stack

Prometheus is an open-source systems monitoring and alerting toolkit that collects and stores its metrics as time series data.

## 📁 Directory Structure

```
prometheus/
├── base/                    # Base configuration
│   ├── hpa.yaml            # Horizontal Pod Autoscaler configuration
│   ├── kustomization.yaml  # Kustomize configuration
│   ├── namespace.yaml      # Namespace definition
│   ├── rbac.yaml           # RBAC permissions
│   ├── service.yaml        # Service definition
│   ├── serviceaccount.yaml # Service account
│   └── values.yaml         # Helm values
└── README.md               # This file
```

## 🔧 Configuration

### Base Configuration

- **RBAC**: Properly scoped permissions for metrics collection
- **Security**: Runs as non-root with read-only filesystem
- **Resources**: Default resource requests and limits
- **Storage**: Configurable persistent storage with Longhorn
- **Scaling**: HPA configured for automatic scaling
- **Components**:
  - Prometheus Server
  - Alertmanager
  - Node Exporter
  - Kube State Metrics

### Security Features

- Runs as non-root user
- Read-only filesystem
- Dropped capabilities
- Network policies
- Resource limits
- Pod security policies

## 🚀 Deployment

### Prerequisites

- Kubernetes cluster 1.16+
- Helm 3+
- Kustomize 4.0.0+
- Persistent storage provisioner (e.g., Longhorn)

### Deploying

1. Apply the base configuration:
   ```bash
   kustomize build . | kubectl apply -f -
   ```

2. Verify the deployment:
   ```bash
   kubectl get pods -n monitoring
   kubectl get svc -n monitoring
   ```

## 🔍 Verification

Check if Prometheus is collecting metrics:

```bash
# Port-forward to Prometheus UI
kubectl port-forward svc/prometheus-server -n monitoring 9090:9090

# Then visit http://localhost:9090 in your browser
```

Check HPA status:
```bash
kubectl get hpa -n monitoring
```

## 🔄 Upgrading

1. Update the chart version in `kustomization.yaml`
2. Update the image tags if needed
3. Test with `kustomize build`
4. Commit and push changes
5. ArgoCD will automatically sync the changes

## 📝 Notes

- The Prometheus server is deployed in the `monitoring` namespace
- Uses `system-cluster-critical` priority class
- Configured with proper pod disruption budget
- Includes HPA for automatic scaling
- Storage is backed by Longhorn with 50Gi persistent volume

## 🔐 Security Considerations

- All pods run as non-root users
- Filesystem is read-only where possible
- Network policies restrict ingress/egress
- Resource limits prevent resource exhaustion
- Regular security updates should be applied
