#!/usr/bin/env python3
import sys, yaml, re, ipaddress
from jsonschema import validate, ValidationError

def fail(msg):
    print(f"❌ {msg}")
    sys.exit(1)

if len(sys.argv) != 2:
    fail("Usage: validate-cluster.py <path/to/cluster.yaml>")

yaml_path = sys.argv[1]
schema_path = "scripts/schemas/cluster.schema.json"

try:
    import json
    with open(schema_path) as f:
        schema = json.load(f)
except Exception as e:
    fail(f"Schema load failed: {e}")

try:
    with open(yaml_path) as f:
        cluster = yaml.safe_load(f)
except Exception as e:
    fail(f"Invalid YAML: {e}")

# JSON schema validation
try:
    validate(instance=cluster, schema=schema)
except ValidationError as e:
    fail(f"Schema validation error: {e.message}")

# Hostname rules
hostname_re = re.compile(r"^[a-z0-9-]+$")
for node in cluster.get("masters", []) + cluster.get("workers", []):
    if not hostname_re.match(node["name"]):
        fail(f"Invalid hostname: {node['name']} (must be lowercase alphanumeric or hyphen)")

# IP validation and overlap
all_ips = [n["ip"] for n in cluster.get("masters", []) + cluster.get("workers", [])]
if len(all_ips) != len(set(all_ips)):
    fail("Duplicate IP addresses found")

# All IPs must be in the same /24 subnet (optional policy)
try:
    networks = [ipaddress.IPv4Interface(f"{ip}/24").network for ip in all_ips]
    if len(set(networks)) > 1:
        fail("Not all IPs are in the same /24 subnet")
except Exception as e:
    fail(f"IP subnet validation failed: {e}")

# HA check
if len(cluster["masters"]) < 3 and cluster.get("rke2_ha_mode", True):
    print("⚠️  Less than 3 masters but HA mode is enabled. This may cause instability.")

print("✅ cluster.yaml validation passed.")
