# 🔐 SealedSecrets Key Backup & Restore Guide

This document explains how to backup and restore the SealedSecrets encryption key, which is **critical** for decrypting all existing sealed secrets.

---

## 📦 Backup the Key

1. Export the controller key to a safe location:
```bash
kubectl get secret -n kube-system sealed-secrets-key -o yaml > backup/sealed-secrets-key.yaml
```

2. Store this file securely:
   - Encrypted S3 bucket
   - Git repository with encryption (e.g. SOPS)
   - Password manager (e.g. Bitwarden, 1Password)

---

## 🔁 Restore the Key (e.g. after re-installing SealedSecrets)

1. Apply the backup into the cluster:
```bash
kubectl apply -f backup/sealed-secrets-key.yaml
```

2. Restart the controller:
```bash
kubectl rollout restart deployment sealed-secrets-controller -n kube-system
```

✅ Your existing sealed secrets will now decrypt properly.

---

## 🚨 WARNING

- If the key is lost, all existing SealedSecrets become permanently undecryptable.
- Always verify your backup with:
```bash
diff <(kubectl get secret -n kube-system sealed-secrets-key -o yaml) backup/sealed-secrets-key.yaml
```

---

## ✅ Recommended Practices

- Backup the key immediately after installation.
- Rotate the key only when needed (requires resealing all secrets).
- Store backups in version-controlled but encrypted environments.

---

📁 Backup Location Example:
```
backup/
└── sealed-secrets-key.yaml
```