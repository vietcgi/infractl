# 🗺️ Infractl Command Roadmap

## ✅ Phase 1: Core + GitOps
- `create cluster` — Provision a new cluster
- `reset cluster` — Tear down and rebuild
- `delete cluster` — Full cleanup
- `status cluster` — View cluster health
- `doctor run` — Diagnose issues
- `sync apps` — Manual sync of GitOps apps
- `autosync matched` — Scheduled or filtered sync
- `reapply matched` — Force-reapply manifests

## ✅ Phase 2: Introspection + Validation
- `list clusters` — Show all clusters
- `get cluster` — View detailed cluster metadata
- `summary cluster` — Health summary
- `validate cluster` — YAML/schema validation
- `seal secret` — Encrypt secrets
- `patch config` — Apply config overrides

## ✅ Phase 3: Maintenance + Extensibility
- `upgrade cluster` — Upgrade RKE2 or other stack
- `scan cluster` — Security scanner
- `config set` — Update global CLI config
- `auth login` — Auth to backend or cloud

## ✅ Phase 4: SaaS Readiness
- `plugin install` — Install CLI plugins
- `agent status` — Remote agent heartbeat
- `telemetry status` — View telemetry & logging

---

_This roadmap is a live design guide for expanding infractl into a modular CLI + platform over the next 10 years._