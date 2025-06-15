📊 Prometheus Operator CRDs

This directory contains the Custom Resource Definitions (CRDs) for the Prometheus Operator.

## 📁 Directory Structure

```
prometheus-operator-crds/
├── base/                    # Base configuration
│   ├── crds/               # Individual CRD definitions
│   │   ├── alertmanagerconfigs.yaml
│   │   ├── alertmanagers.yaml
│   │   ├── podmonitors.yaml
│   │   ├── probes.yaml
│   │   ├── prometheuses.yaml
│   │   ├── prometheusrules.yaml
│   │   ├── servicemonitors.yaml
│   │   └── thanosrulers.yaml
│   ├── kustomization.yaml  # Kustomize configuration
│   └── namespace.yaml      # Namespace definition
└── README.md               # This file
```

## 🔧 CRDs Included

1. **Alertmanager**
   - `alertmanagers.monitoring.coreos.com`
   - `alertmanagerconfigs.monitoring.coreos.com`

2. **Prometheus**
   - `prometheuses.monitoring.coreos.com`
   - `prometheusrules.monitoring.coreos.com`

3. **Monitoring**
   - `servicemonitors.monitoring.coreos.com`
   - `podmonitors.monitoring.coreos.com`
   - `probes.monitoring.coreos.com`

4. **Thanos**
   - `thanosrulers.monitoring.coreos.com`

## 🚀 Deployment

These CRDs are automatically deployed as part of the ArgoCD application set.

### Manual Deployment

To deploy manually:

```bash
kustomize build . | kubectl apply -f -
```

### Verifying the Installation

Check that all CRDs are installed:

```bash
kubectl get crd | grep "monitoring.coreos.com"
```

## 🔄 Upgrading

To upgrade the CRDs:

1. Update the CRD YAML files in the `crds/` directory
2. Commit and push the changes
3. ArgoCD will automatically apply the updates

## 🔐 Security

- All CRDs are installed in the `monitoring` namespace
- CRDs are managed by ArgoCD with proper sync policies
- Each CRD includes annotations for proper ArgoCD handling

## 📝 Notes

- These CRDs are required for the Prometheus Operator to function
- The CRD versions should match the version of the Prometheus Operator being used
- CRD updates should be tested in a non-production environment first
