# Kubernetes GitOps Repository

This repository contains the GitOps configurations for managing Kubernetes clusters using ArgoCD. It follows the [app of apps pattern](https://argo-cd.readthedocs.io/en/stable/operator-manual/cluster-bootstrapping/) and uses Kustomize for environment-specific customizations.

## Directory Structure

```
apps/
├── gitops/               # GitOps tooling configurations
│   └── argocd/           # ArgoCD ApplicationSets and configurations
│       ├── dev/          # Development environment
│       └── prod/         # Production environment
└── system/               # System components
    ├── base/             # Base configurations
    ├── components/       # Reusable Kustomize components
    └── overlays/         # Environment-specific configurations
        ├── dev/          # Development overlay
        └── prod/         # Production overlay
            ├── shared/   # Shared production configurations
            ├── dc11a/    # DC11A cluster configurations
            └── dc11b/    # DC11B cluster configurations
```

## Getting Started

### Prerequisites

- Kubernetes cluster with ArgoCD installed
- `kubectl` configured with cluster admin access
- `kustomize` (v4.5.0+)
- `argocd` CLI (v2.4.0+)

### Bootstrapping a New Cluster

1. Install ArgoCD:
   ```bash
   kubectl create namespace argocd
   kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml
   ```

2. Apply the root application:
   ```bash
   # For development
   kubectl apply -f gitops/argocd/dev/root-app.yaml
   
   # For production (dc11a)
   kubectl apply -f gitops/argocd/prod/dc11a/root-app.yaml
   ```

## Development Workflow

1. **Create a new component**:
   - Add base manifests in `system/base/<component-name>`
   - Create overlays in `system/overlays/<env>/<component-name>`

2. **Update configurations**:
   - Modify the appropriate overlay for environment-specific changes
   - Use Kustomize patches for non-destructive updates

3. **Apply changes**:
   ```bash
   # Preview changes
   kustomize build system/overlays/dev/<component-name>
   
   # Apply to cluster (if not using GitOps)
   kustomize build system/overlays/dev/<component-name> | kubectl apply -f -
   ```

## Best Practices

1. **Kustomize**:
   - Use `commonLabels` and `commonAnnotations` consistently
   - Prefer JSON patches over strategic merge patches
   - Use components for shared configurations

2. **GitOps**:
   - Keep manifests declarative
   - Avoid manual changes to the cluster
   - Use sync waves for ordering

3. **Security**:
   - Use namespaces for isolation
   - Implement network policies
   - Set resource limits and requests

## Troubleshooting

### Common Issues

1. **Sync Failures**:
   - Check ArgoCD logs: `kubectl logs -n argocd -l app.kubernetes.io/name=argocd-application-controller`
   - Verify resource quotas and limits
   - Check for RBAC issues

2. **Configuration Drift**:
   ```bash
   # Detect drift
   argocd app diff <app-name>
   
   # Sync application
   argocd app sync <app-name>
   ```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Open a pull request

## License

[Your License Here]
