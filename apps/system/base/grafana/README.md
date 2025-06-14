# 📊 Grafana Monitoring Dashboard

Grafana is an open-source platform for monitoring and observability, allowing you to query, visualize, alert on, and understand your metrics.

## 📁 Directory Structure

```
grafana/
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

- **RBAC**: Properly scoped permissions for metrics visualization
- **Security**: Runs as non-root with read-only filesystem
- **Resources**: Default resource requests and limits
- **Storage**: Configurable persistent storage with Longhorn
- **Scaling**: HPA configured for automatic scaling
- **Authentication**: Basic auth with secure defaults

### Security Features

- Runs as non-root user (UID 472)
- Read-only filesystem where possible
- Dropped capabilities
- Resource limits to prevent resource exhaustion
- Secure default configuration
- Disabled unnecessary authentication methods
- Secure headers enabled

## 🚀 Deployment

### Prerequisites

- Kubernetes cluster 1.16+
- Helm 3+
- Kustomize 4.0.0+
- Persistent storage provisioner (e.g., Longhorn)
- Prometheus instance (for metrics)

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

## 🔍 Accessing Grafana

1. Port-forward to the Grafana service:
   ```bash
   kubectl port-forward svc/grafana -n monitoring 3000:80
   ```

2. Open http://localhost:3000 in your browser

3. Default credentials:
   - Username: admin
   - Password: admin (change this in production!)

## 🔄 Upgrading

1. Update the chart version in `kustomization.yaml`
2. Update the image tag if needed
3. Test with `kustomize build`
4. Commit and push changes
5. ArgoCD will automatically sync the changes

## 📝 Notes

- The Grafana server is deployed in the `monitoring` namespace
- Uses `longhorn` for persistent storage by default
- Includes HPA for automatic scaling
- Pre-configured with Prometheus as the default datasource

## 🔐 Security Considerations

- Change the default admin password in production
- Enable proper authentication (OAuth2, LDAP, etc.)
- Use network policies to restrict access
- Regularly update to the latest version
- Monitor resource usage and adjust limits as needed
- Consider enabling TLS for production deployments

## 📊 Dashboards

Dashboards can be provisioned by adding them to the `dashboards` directory. They will be automatically loaded by Grafana.

## 🔌 Plugins

Additional plugins can be installed by adding them to the `plugins` section in `values.yaml`.

## 🔍 Troubleshooting

Check the Grafana pod logs:
```bash
kubectl logs -n monitoring -l app.kubernetes.io/name=grafana --tail=100 -f
```

Check the status of the deployment:
```bash
kubectl get pods -n monitoring -l app.kubernetes.io/name=grafana
kubectl describe pod -n monitoring -l app.kubernetes.io/name=grafana
```

## 🔗 Related Resources

- [Grafana Documentation](https://grafana.com/docs/)
- [Grafana Helm Chart](https://github.com/grafana/helm-charts/tree/main/charts/grafana)
- [Prometheus Operator](https://github.com/prometheus-operator/prometheus-operator)
