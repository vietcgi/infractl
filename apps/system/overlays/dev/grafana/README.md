# 🔐 SealedSecrets Guide for Grafana (Dev)

This folder contains a SealedSecret that securely manages the `admin-password` for Grafana.

## 📦 What's included

- `sealed-grafana-secret.yaml`: A SealedSecret object that holds an encrypted `admin-password`
- `kustomization.yaml`: Includes this secret as part of the overlay

---

## 🛠 How to Create/Update a SealedSecret

1. Create a Kubernetes Secret locally:
```bash
kubectl create secret generic grafana-admin \
  --from-literal=admin-password='YourSecurePassword' \
  --namespace=grafana \
  --dry-run=client -o json
```

2. Encrypt it using your cluster’s SealedSecrets public key:
```bash
kubeseal --format=yaml --cert my-cluster-pub-cert.pem > sealed-grafana-secret.yaml
```

> Replace `my-cluster-pub-cert.pem` with your real `kubeseal --fetch-cert` output

3. Replace the existing file:
```bash
mv sealed-grafana-secret.yaml apps/system/overlays/dev/grafana/
```

4. Commit the new sealed secret:
```bash
git add .
git commit -m "Update sealed Grafana secret"
git push
```

---

## 🔄 Rotate Secrets

Just repeat the above steps with a new value. SealedSecrets ensures they can only be decrypted by the controller in your cluster.

## 📎 Note

- This secret is only valid for the namespace `grafana`
- You must have SealedSecrets controller installed
