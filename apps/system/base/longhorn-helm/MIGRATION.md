# Longhorn Migration to Helm

This document outlines the steps to migrate from the current Longhorn installation to the new Helm-based installation.

## Prerequisites

1. Backup all Longhorn volumes and snapshots
2. Ensure you have `kubectl` and `helm` installed
3. Verify you have cluster admin access

## Migration Steps

### 1. Backup Current Configuration

```bash
# Backup current Longhorn resources
kubectl -n longhorn-system get all -o yaml > longhorn-backup.yaml
kubectl -n longhorn-system get volumes.longhorn.io -o yaml > longhorn-volumes-backup.yaml
kubectl -n longhorn-system get settings.longhorn.io -o yaml > longhorn-settings-backup.yaml
```

### 2. Uninstall Current Longhorn

```bash
# Delete the current Longhorn installation
kubectl delete -f /path/to/current/longhorn/manifests/

# Wait for all Longhorn pods to terminate
kubectl -n longhorn-system get pods
```

### 3. Install New Helm-based Longhorn

1. Add the Longhorn Helm repository:
   ```bash
   helm repo add longhorn https://charts.longhorn.io
   helm repo update
   ```

2. Create the namespace if it doesn't exist:
   ```bash
   kubectl create namespace longhorn-system
   ```

3. Install using Kustomize:
   ```bash
   kustomize build /path/to/longhorn-helm/ | kubectl apply -f -
   ```

### 4. Verify Installation

```bash
# Check all pods are running
kubectl -n longhorn-system get pods

# Verify storage class is created
kubectl get storageclass

# Check Longhorn UI (if ingress is enabled)
kubectl -n longhorn-system get ingress
```

### 5. Restore Volumes (if needed)

If you had existing volumes, they should be automatically detected. Verify with:

```bash
kubectl -n longhorn-system get volumes.longhorn.io
```

## Rollback

If you need to rollback to the previous installation:

```bash
# Uninstall Helm-based Longhorn
kustomize build /path/to/longhorn-helm/ | kubectl delete -f -

# Reinstall previous version
kubectl apply -f longhorn-backup.yaml
```

## Post-Migration

1. Update any applications using Longhorn storage to use the new StorageClass if needed
2. Monitor the system for any issues
3. Clean up old resources after confirming the new installation is stable
