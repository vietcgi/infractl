# 🔐 ArgoCD RBAC Model (SSO + AppProject-Based)

This document outlines the Role-Based Access Control (RBAC) model currently enforced in ArgoCD using Okta groups and AppProjects.

---

## ✅ SSO Integration

- **Provider**: Okta
- **OIDC Claim for Groups**: `groups`
- **Mapped via**: `argocd-cm` and `argocd-rbac-cm`

---

## 🎯 AppProject-Based Access

### `dev` Project

- **Namespace**: `dev`
- **Source Git Repo**: `https://github.com/your-org/apps`
- **Access Window**: unrestricted
- **Group**: `okta-devops-dev`
- **Role**: `developer`
- **Permissions**:
  - Sync applications in `dev/*`
  - View status of applications

```csv
p, proj:dev:developer, applications, sync, dev/*, allow
p, proj:dev:developer, applications, get, dev/*, allow
g, okta-devops-dev, role:developer
```

---

### `prod` Project

- **Namespace**: `prod`
- **Source Git Repo**: `https://github.com/your-org/apps`
- **Access Window**: Monday–Friday, 9am–5pm PT
- **Group**: `okta-prod-ops`
- **Role**: `ops`
- **Permissions**:
  - Sync applications in `prod/*`
  - View status of applications

```csv
p, proj:prod:ops, applications, sync, prod/*, allow
p, proj:prod:ops, applications, get, prod/*, allow
g, okta-prod-ops, role:ops
```

---

## 🛡️ Global Defaults

- **Default Role**: `readonly`
- **Access**:
  - View ArgoCD apps only (no sync, no edit)

```yaml
policy.default: role:readonly
```

---

## 🔐 Notes

- These roles apply to apps within their `AppProject` only.
- All access is scoped to:
  - approved Git repos
  - approved destinations (namespace + cluster)
  - defined sync times (for `prod`)

---

## 🧠 Recommendation

- Regularly audit group membership in Okta.
- Extend `AppProjects` for team-based scoping if needed.
- Rotate secrets or role bindings if suspicious activity occurs.