import pytest
import yaml
from jsonschema import validate, ValidationError

CLUSTER_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "region": {"type": "string"},
        "env": {"type": "string"},
        "nodes": {"type": "array"},
    },
    "required": ["name", "region", "env"]
}

def test_valid_cluster_yaml():
    data = {
        "name": "kevin-vu",
        "region": "us-west",
        "env": "dev",
        "nodes": [{"role": "master"}, {"role": "worker"}]
    }
    validate(instance=data, schema=CLUSTER_SCHEMA)

def test_invalid_cluster_yaml():
    bad_data = {
        "region": "us-west"
    }
    with pytest.raises(ValidationError):
        validate(instance=bad_data, schema=CLUSTER_SCHEMA)