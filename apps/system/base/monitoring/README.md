# 📊 Monitoring Stack

This directory contains the base configuration for the Kubernetes monitoring stack, including Prometheus, Grafana, and Alertmanager.

## 📁 Directory Structure

```
monitoring/
├── base/                    # Base configuration
│   └── network-policies.yaml # Network policies for monitoring components
├── overlays/
│   ├── dev/                 # Development environment
│   │   └── monitoring/
│   │       ├── kustomization.yaml
│   │       ├── network-policy.yaml
│   │       ├── pdb.yaml
│   │       └── service-monitor.yaml
│   └── prod/                # Production environment
│       ├── dc11a/           # DC11A specific config
│       │   └── monitoring/
│       │       ├── kustomization.yaml
│       │       ├── network-policy.yaml
│       │       ├── pdb.yaml
│       │       └── service-monitor.yaml
│       └── dc11b/           # DC11B specific config
│           └── monitoring/
│               ├── kustomization.yaml
│               ├── network-policy.yaml
│               ├── pdb.yaml
│               └── service-monitor.yaml
└── README.md                # This file
```

## 🔧 Configuration

### Base Configuration

- **Network Policies**: Default deny-all with specific allow rules for monitoring traffic
- **RBAC**: Least-privilege service accounts and roles
- **Security Context**: Non-root execution, read-only filesystem, dropped capabilities

### Production Overlay (dc11a/dc11b)

- **High Availability**: Multiple replicas with pod anti-affinity
- **Resource Limits**: Optimized requests/limits for production workloads
- **Security**:
  - Network policies restricting traffic to authorized sources
  - TLS for all internal communication
  - Read-only filesystem and non-root execution
  - Seccomp and AppArmor profiles
- **Resilience**:
  - Pod disruption budgets for HA
  - Node and zone anti-affinity
  - Liveness/readiness probes

## 🚀 Deployment

### Prerequisites

- Kubernetes cluster 1.20+
- Cert-manager for TLS certificates
- Prometheus Operator CRDs installed
- Sufficient node resources

### Deploying with ArgoCD

The monitoring stack is deployed as part of the GitOps workflow. ArgoCD will automatically sync the configuration from Git.

### Manual Deployment

```bash
# Apply base configuration
kustomize build base | kubectl apply -f -

# Apply production overlay for dc11a
kustomize build overlays/prod/dc11a/monitoring | kubectl apply -f -
```

## 🔍 Verification

```bash
# Check pod status
kubectl get pods -n monitoring

# Check Prometheus status
kubectl port-forward -n monitoring svc/prometheus 9090:9090 &
open http://localhost:9090

# Check Grafana (default credentials: admin/prom-operator)
kubectl port-forward -n monitoring svc/grafana 3000:3000 &
open http://localhost:3000

# Check Alertmanager
kubectl port-forward -n monitoring svc/alertmanager 9093:9093 &
open http://localhost:9093
```

## 🔐 Security Hardening

### Network Security
- All components run with network policies
- Ingress limited to required ports
- Egress restricted to necessary destinations
- TLS required for all internal communication

### Pod Security
- Non-root user execution (1000:1000)
- Read-only root filesystem
- All Linux capabilities dropped
- Seccomp and AppArmor profiles
- Resource limits and requests

### Authentication & Authorization
- RBAC with least privilege
- Service accounts with minimal permissions
- Token-based authentication for Prometheus
- Grafana OAuth2 integration recommended

## 📝 Operational Notes

### Monitoring the Monitoring Stack

Key metrics to monitor:
- `prometheus_tsdb_head_series`: Total number of series
- `prometheus_tsdb_head_samples_appended_total`: Rate of samples ingested
- `prometheus_http_requests_total`: API request rate
- `container_memory_working_set_bytes`: Memory usage
- `container_cpu_usage_seconds_total`: CPU usage

### Scaling

Adjust the following based on cluster size:
- `prometheus.retention`: 15-30 days for production
- `prometheus.retentionSize`: 50-100GB
- `prometheus.replicas`: 2-3 for HA
- Resource requests/limits based on workload

### Backup & Restore

#### Prometheus Data

```bash
# Create backup
kubectl exec -n monitoring prometheus-0 -- tar czf /tmp/prom-data-backup.tar.gz -C /prometheus .
kubectl cp monitoring/prometheus-0:/tmp/prom-data-backup.tar.gz prom-data-backup.tar.gz

# Restore
kubectl cp prom-data-backup.tar.gz monitoring/prometheus-0:/tmp/prom-data-backup.tar.gz
kubectl exec -n monitoring prometheus-0 -- sh -c 'cd /prometheus && tar xzf /tmp/prom-data-backup.tar.gz'
```

#### Grafana Dashboards

1. Export dashboards using the UI or API
2. Store JSON definitions in version control
3. Use ConfigMaps or Grafana provisioning for automated deployment

### Troubleshooting

#### Prometheus

```bash
# Check logs
kubectl logs -n monitoring -l app.kubernetes.io/name=prometheus

# Check storage
kubectl exec -n monitoring prometheus-0 -- df -h /prometheus

# Check configuration
kubectl exec -n monitoring prometheus-0 -- wget -qO- localhost:9090/-/healthy
kubectl exec -n monitoring prometheus-0 -- wget -qO- localhost:9090/-/ready
```

#### Alertmanager

```bash
# Check logs
kubectl logs -n monitoring -l app.kubernetes.io/name=alertmanager

# Check configuration
kubectl port-forward -n monitoring svc/alertmanager 9093:9093 &
curl http://localhost:9093/-/ready
```

## 📚 References

- [Prometheus Documentation](https://prometheus.io/docs/)
- [Grafana Documentation](https://grafana.com/docs/)
- [Alertmanager Documentation](https://prometheus.io/docs/alerting/latest/alertmanager/)
- [Kubernetes Monitoring Architecture](https://kubernetes.io/docs/concepts/cluster-administration/monitoring/)
