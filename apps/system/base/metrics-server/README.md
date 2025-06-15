# 📊 Metrics Server

Kubernetes Metrics Server collects resource metrics from kubelets and exposes them in the Kubernetes API server through the Metrics API for use by the Horizontal Pod Autoscaler and Vertical Pod Autoscaler.

## 📁 Directory Structure

```
metrics-server/
├── base/                    # Base configuration
│   ├── network-policies.yaml # Network policies for metrics server
│   ├── values.yaml          # Helm values with security defaults
│   └── kustomization.yaml   # Kustomize configuration
├── overlays/
│   ├── dev/                 # Development environment
│   │   └── metrics-server/
│   │       ├── kustomization.yaml
│   │       ├── network-policy.yaml
│   │       └── hpa.yaml
│   └── prod/                # Production environment
│       ├── dc11a/           # DC11A specific config
│       │   └── metrics-server/
│       │       ├── kustomization.yaml
│       │       └── network-policy.yaml
│       └── dc11b/           # DC11B specific config
│           └── metrics-server/
│               ├── kustomization.yaml
│               └── network-policy.yaml
└── README.md                # This file
```

## 🔧 Configuration

### Base Configuration

- **RBAC**: Least-privilege permissions for metrics collection
- **Security**:
  - Runs as non-root (UID 1000)
  - Read-only filesystem
  - All Linux capabilities dropped
  - Seccomp profile enabled
  - Network policies applied
- **Resources**: Optimized requests/limits
- **Probes**: Configured for reliability
- **TLS**: Modern cipher suites and TLS 1.2+ enforced

### Development Overlay

- Single replica with node anti-affinity
- Reduced resource limits
- Development-specific labels and annotations
- HPA with conservative scaling
- Network policy allowing access from dev namespaces

### Production Overlays (dc11a/dc11b)

- Multiple replicas (3) with pod anti-affinity
- High availability configuration
- Production-grade resource limits
- Zone-aware topology spread constraints
- Strict network policies
- Priority class: system-cluster-critical
- Pod disruption budget (minAvailable: 2)

## 🚀 Deployment

### Prerequisites

- Kubernetes cluster 1.20+
- Helm 3.6.0+
- Cert-manager (for TLS)
- Sufficient permissions to create ClusterRole and ClusterRoleBinding

### Deploying with ArgoCD

1. The metrics-server is deployed as part of the GitOps workflow
2. ArgoCD will automatically sync the configuration from Git
3. Verify deployment:
   ```bash
   kubectl get deployment metrics-server -n kube-system
   kubectl get apiservice v1beta1.metrics.k8s.io
   kubectl top nodes
   ```

## 🔍 Verification

Check if metrics are being collected and verify security settings:

```bash
# Check metrics server status
kubectl get --raw /apis/metrics.k8s.io/v1beta1/nodes | jq .

# Verify security context
kubectl get pod -n kube-system -l k8s-app=metrics-server -o json | jq '.items[].spec.containers[].securityContext'

# Check network policies
kubectl get networkpolicies -n kube-system

# Verify metrics collection
kubectl top nodes
kubectl top pods -A
```

## 🔄 Upgrading

1. Update the container image version in `values.yaml`
2. Test with `kustomize build`
3. Commit and push changes to the appropriate branch
4. ArgoCD will automatically sync the changes
5. Monitor the rollout:
   ```bash
   kubectl rollout status deployment/metrics-server -n kube-system
   ```

## 🔐 Security Hardening

### Network Policies
- Restricts ingress to kube-system and monitoring namespaces
- Egress is allowed to kubelet (10250) and DNS (53)
- Zone-aware traffic routing in production

### Pod Security
- Runs as non-root user (1000:1000)
- Read-only root filesystem
- All capabilities dropped
- Seccomp profile enabled
- Resource limits enforced

### TLS Configuration
- TLS 1.2+ required
- Modern cipher suites only
- Certificate rotation managed by cert-manager

### High Availability
- Multiple replicas with anti-affinity
- Pod disruption budget (minAvailable: 2)
- Priority class: system-cluster-critical
- Topology spread across failure domains

## 📝 Operational Notes

### Troubleshooting

#### Metrics Not Available
```bash
# Check metrics server logs
kubectl logs -n kube-system -l k8s-app=metrics-server

# Check API service status
kubectl get apiservice v1beta1.metrics.k8s.io -o yaml

# Check kubelet connectivity
kubectl get --raw /api/v1/nodes/$(kubectl get nodes -o jsonpath='{.items[0].metadata.name}')/proxy/metrics/resource
```

#### Performance Issues
- Check resource usage: `kubectl top pod -n kube-system -l k8s-app=metrics-server`
- Review metrics resolution settings in `values.yaml`
- Verify node resources and kubelet configuration

### Monitoring
- Prometheus ServiceMonitor configured for metrics collection
- Key metrics:
  - `metrics_server_kubelet_request_duration_seconds`
  - `metrics_server_scraper_duration_seconds`
  - `metrics_server_scraper_last_time_seconds`
  - `process_resident_memory_bytes`

### Backup
- Configuration is stored in Git (this repository)
- No persistent volumes to back up
- RBAC and CRDs can be exported if needed:
  ```bash
  kubectl get clusterrole,clusterrolebinding -l app.kubernetes.io/name=metrics-server -o yaml > metrics-server-rbac.yaml
  ```

## 📚 References

- [Metrics Server Documentation](https://github.com/kubernetes-sigs/metrics-server)
- [Kubernetes Metrics Server Security](https://kubernetes.io/docs/tasks/debug-application-cluster/resource-metrics-pipeline/#metrics-server)
- [Pod Security Standards](https://kubernetes.io/docs/concepts/security/pod-security-standards/)

- The metrics server is deployed in the `metrics-server` namespace
- Uses `system-cluster-critical` priority class
- Configured with proper pod disruption budget
- Includes HPA for automatic scaling
