# ArgoCD Cluster Management Design

## Overview
This document outlines the design for managing multiple Kubernetes clusters using ArgoCD, with a focus on maintaining a single source of truth while allowing for cluster-specific customizations. The bootstrap process is implemented in Python (`infractl/modules/addons.py`), and each ArgoCD instance manages its own configuration through GitOps using Kustomize components.

## Goals
- Each cluster has its own ArgoCD instance with cluster-specific configurations
- ArgoCD manages its own configuration through GitOps
- No code duplication across clusters using Kustomize components
- Easy to add new clusters with minimal configuration
- Consistent configuration management across environments
- Clear separation of concerns between shared and cluster-specific settings

## Directory Structure
```
apps/system/
├── base/                    # Common configurations
│   └── argocd/             # Base ArgoCD configuration
│       ├── application.yaml # ArgoCD self-management Application
│       └── kustomization.yaml # Base kustomization
│
├── components/             # Reusable Kustomize components
│   └── argocd/
│       └── cluster/      # Cluster-specific configurations
│           └── kustomization.yaml
│
└── overlays/
    ├── dev/                # Development environment
    │   └── argocd/
    │       └── kustomization.yaml
    │
    └── prod/               # Production environment
        ├── argocd/           # Shared prod config
        │   └── kustomization.yaml
        │
        ├── dc11a/           # DC11A cluster
        │   └── argocd/
        │       └── kustomization.yaml
        │
        └── dc11b/           # DC11B cluster
            └── argocd/
                └── kustomization.yaml
```

## Components

### 1. Base Configuration
- Common configurations shared across all clusters
- Default values and settings
- Resource definitions
- Common labels and annotations

### 2. ArgoCD Self-Management
- Initial ArgoCD installation is done via bootstrap
- ArgoCD then manages its own configuration through GitOps
- ArgoCD Application points to its own configuration in Git
- Configuration includes:
  - RBAC policies
  - Network policies
  - Resource settings
  - OIDC configuration
  - Other ArgoCD settings

### 3. Python Bootstrap
- Handles initial cluster setup
- Processes templates
- Manages cluster registration
- Configures ArgoCD installation
- Sets up initial GitOps configuration

## Implementation Steps

### Phase 1: Python Bootstrap Development
1. Create Python bootstrap framework
   ```python
   # bootstrap.py
   class ClusterBootstrap:
       def __init__(self, cluster_name, config):
           self.cluster_name = cluster_name
           self.config = config
           
       def install_argocd(self):
           # Install ArgoCD
           pass
           
       def configure_argocd(self):
           # Configure ArgoCD for self-management
           pass
           
       def setup_gitops(self):
           # Set up initial GitOps configuration
           pass
   ```

2. Implement template processing
   ```python
   # templates.py
   class TemplateProcessor:
       def process_templates(self, cluster_name):
           # Process all templates for the cluster
           pass
           
       def generate_patches(self):
           # Generate cluster-specific patches
           pass
   ```

### Phase 2: ArgoCD Self-Management
1. Create ArgoCD self-management application
   ```yaml
   # base/argocd/application.yaml
   apiVersion: argoproj.io/v1alpha1
   kind: Application
   metadata:
     name: argocd
     namespace: argocd
   spec:
     project: default
     source:
       repoURL: https://github.com/your-org/your-repo.git
       targetRevision: HEAD
       path: apps/system/overlays/prod/argocd
     destination:
       server: https://kubernetes.default.svc
       namespace: argocd
   ```

2. Configure ArgoCD to manage itself
   - Set up RBAC for self-management
   - Configure network policies
   - Set up monitoring
   - Configure OIDC

### Phase 3: Cluster Management
1. Test with existing clusters
   - DC11A
   - DC11B

2. Document the system
   - Setup instructions
   - Usage guidelines
   - Troubleshooting guide

## Bootstrap Process

### 1. Initial Setup
```python
# infractl/modules/addons.py
def bootstrap_gitops_stack(
    env: str,
    cluster: str = None,
    install_flux: bool = False,
    install_fleet: bool = False,
    skip_argocd: bool = False,
    kubeconfig_path: str = None
) -> None:
    # 1. Install ArgoCD via Helm
    if not skip_argocd:
        install_argocd(env, kubeconfig_path)
        
    # 2. Apply self-management Application
    if not skip_argocd:
        # Determine overlay path based on env and cluster
        overlay_path = determine_overlay_path(env, cluster)
        apply_kustomize(overlay_path, kubeconfig_path)
    
    # 3. Set up other GitOps components if needed
    if install_flux:
        install_flux()
    if install_fleet:
        install_fleet()
```

### 2. Cluster Configuration
Each cluster's configuration is defined in its overlay directory:

```yaml
# Example: apps/system/overlays/prod/dc11a/argocd/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: argocd

# Include the base prod configuration
resources:
  - ../../argocd

# Include shared components
components:
  - ../../../../components/argocd/cluster

# Set cluster-specific values
configMapGenerator:
  - name: cluster-config
    literals:
      - CLUSTER_NAME=dc11a
      - INGRESS_HOST=argocd.dc11a.prod.example.com

vars:
  - name: CLUSTER_NAME
    objref:
      kind: ConfigMap
      name: cluster-config
      apiVersion: v1
    fieldref:
      fieldpath: data.CLUSTER_NAME
  - name: INGRESS_HOST
    objref:
      kind: ConfigMap
      name: cluster-config
      apiVersion: v1
    fieldref:
      fieldpath: data.INGRESS_HOST
```

### 2. ArgoCD Self-Management
1. ArgoCD is installed via bootstrap
2. ArgoCD Application is created pointing to its own config
3. ArgoCD reads its configuration from Git
4. ArgoCD applies its own configuration
5. ArgoCD then manages other applications

## Benefits
1. **DRY (Don't Repeat Yourself)**
   - Single source of truth in base configurations
   - Shared Kustomize components eliminate duplication
   - Consistent configurations across clusters

2. **Maintainability**
   - Update common configurations in one place (components/)
   - Clear separation between shared and cluster-specific settings
   - Add new clusters by creating minimal configuration
   - Easy to understand directory structure

3. **Reliability**
   - Consistent deployment process using Kustomize
   - Automated configuration generation with variables
   - Reduced human error through component reuse

4. **GitOps**
   - All configurations in Git with proper versioning
   - Audit trail of all changes
   - Automated updates through ArgoCD self-management
   - Environment and cluster-specific overrides in a structured way

## Security Considerations
1. **Access Control**
   - Cluster-specific RBAC
   - Secure communication
   - Secret management

2. **Compliance**
   - Audit logging
   - Configuration validation
   - Security scanning

## Next Steps
1. [x] Implement Python bootstrap framework in `infractl/modules/addons.py`
2. [x] Create ArgoCD self-management configuration with Kustomize components
3. [x] Set up cluster-specific configurations for dc11a and dc11b
4. [x] Document the system (this document)
5. [ ] Add validation tests for Kustomize configurations
6. [ ] Document the bootstrap process and requirements
7. [ ] Create examples for adding new clusters
5. [ ] Create maintenance procedures 