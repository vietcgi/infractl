# GitOps Bootstrap Process

This document outlines the GitOps bootstrap process used for deploying and managing Kubernetes clusters with ArgoCD.

## Overview

The GitOps bootstrap process is responsible for:
1. Installing and configuring ArgoCD
2. Setting up the root application that manages all other applications
3. Applying cluster-specific configurations
4. Ensuring proper environment segregation

## Configuration Hierarchy

### Values File Resolution

When installing components (like ArgoCD), the system looks for configuration files in this order:

1. **Cluster-specific values** (highest priority):
   ```
   apps/system/overlays/{env}/{cluster}/{component}/values.yaml
   ```
   Example: `apps/system/overlays/prod/dc11a/argocd/values.yaml`

2. **Environment-specific values**:
   ```
   apps/system/overlays/{env}/{component}/values.yaml
   ```
   Example: `apps/system/overlays/prod/argocd/values.yaml`

3. **Base values** (lowest priority):
   ```
   apps/system/base/{component}/values.yaml
   ```
   Example: `apps/system/base/argocd/values.yaml`

The first matching file found in this order will be used. This allows for flexible configuration overrides at different levels.

### Root Application Resolution

For the root ArgoCD application, the system looks for:

1. **Cluster-specific root app**:
   ```
   apps/gitops/argocd/{env}/{cluster}/root-app.yaml
   ```
   Example: `apps/gitops/argocd/prod/dc11a/root-app.yaml`

2. **Environment root app** (fallback):
   ```
   apps/gitops/argocd/{env}/root-app.yaml
   ```
   Example: `apps/gitops/argocd/prod/root-app.yaml`

## Bootstrapping a New Cluster

When creating a new cluster, the following happens:

1. The cluster is provisioned with RKE2
2. CoreDNS is installed
3. Sealed Secrets key is created (if needed)
4. ArgoCD is installed with the appropriate values file
5. The root application is applied
6. ArgoCD takes over management of all other applications

### Example: Creating a New Production Cluster

```bash
# Create a new production cluster named dc11a
infractl create cluster --name dc11a --env prod --region us-east
```

This will:
1. Look for cluster-specific configurations in `apps/system/overlays/prod/dc11a/`
2. Fall back to environment configurations in `apps/system/overlays/prod/`
3. Finally use base configurations in `apps/system/base/`

## Adding a New Component

To add a new component to be managed by ArgoCD:

1. Create base manifests in `apps/system/base/{component}/`
2. Add environment-specific overrides in `apps/system/overlays/{env}/{component}/`
3. Add cluster-specific overrides if needed in `apps/system/overlays/{env}/{cluster}/{component}/`
4. Reference the component in the appropriate Application or ApplicationSet

## Troubleshooting

### Common Issues

1. **Missing Values File**
   - Error: `No values file found for {component} in env={env}, cluster={cluster}`
   - Solution: Ensure at least the base values file exists at `apps/system/base/{component}/values.yaml`

2. **Root Application Not Found**
   - Error: `Root application not found. Expected file: {path}`
   - Solution: Create the root application file at the expected location

3. **Configuration Not Applied**
   - Check the logs for which values file was used
   - Verify the configuration hierarchy is correct

## Best Practices

1. **Configuration Management**
   - Keep common configurations in base
   - Use environment overrides sparingly
   - Document any non-obvious overrides

2. **Secret Management**
   - Use Sealed Secrets for sensitive data
   - Store sealed secrets in version control
   - Rotate keys regularly

3. **GitOps Principles**
   - Everything as code
   - Single source of truth in Git
   - Automated deployment and rollback
