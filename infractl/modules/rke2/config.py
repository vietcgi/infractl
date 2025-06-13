"""RKE2 module configuration management.

This module handles configuration loading from multiple sources with the following precedence:
1. Explicitly passed parameters
2. Environment variables
3. Configuration files
4. Default values
"""
import os
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List, Union
import yaml
from pydantic import BaseModel, Field, validator, root_validator

logger = logging.getLogger("rke2.config")

# Default configuration paths
DEFAULT_CONFIG_PATHS = [
    Path("/etc/emodo/rke2/config.yaml"),
    Path("~/.config/emodo/rke2/config.yaml").expanduser(),
    Path("rke2-config.yaml").absolute(),
]

class SSHConfig(BaseModel):
    """SSH connection configuration."""
    user: str = Field(
        default="ubuntu",
        env="RKE2_SSH_USER",
        description="Default SSH username"
    )
    key_path: str = Field(
        default="~/.ssh/id_rsa",
        env="RKE2_SSH_KEY_PATH",
        description="Path to SSH private key"
    )
    port: int = Field(
        default=22,
        env="RKE2_SSH_PORT",
        description="SSH port number"
    )
    connect_timeout: int = Field(
        default=10,
        env="RKE2_SSH_CONNECT_TIMEOUT",
        description="SSH connection timeout in seconds"
    )
    command_timeout: int = Field(
        default=120,
        env="RKE2_SSH_CMD_TIMEOUT",
        description="SSH command execution timeout in seconds"
    )
    retry_attempts: int = Field(
        default=3,
        env="RKE2_SSH_RETRY_ATTEMPTS",
        description="Number of SSH connection retry attempts"
    )

    @validator('key_path')
    def expand_key_path(cls, v: str) -> str:
        """Expand the user home directory in the key path."""
        return os.path.expanduser(v)

class LoggingConfig(BaseModel):
    """Logging configuration."""
    level: str = Field(
        default="INFO",
        env="RKE2_LOG_LEVEL",
        description="Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)"
    )
    file: Optional[str] = Field(
        default=None,
        env="RKE2_LOG_FILE",
        description="Path to log file (if None, logs to stderr)"
    )
    max_size_mb: int = Field(
        default=100,
        env="RKE2_LOG_MAX_SIZE_MB",
        description="Maximum log file size in MB before rotation"
    )
    backup_count: int = Field(
        default=5,
        env="RKE2_LOG_BACKUP_COUNT",
        description="Number of backup log files to keep"
    )

class ClusterConfig(BaseModel):
    """Cluster-wide configuration."""
    token: Optional[str] = Field(
        default=None,
        env="RKE2_CLUSTER_TOKEN",
        description="Cluster token for node authentication"
    )
    interface: str = Field(
        default="bond0.100",
        env="RKE2_INTERFACE",
        description="Network interface for node IP detection"
    )
    service_cidr: str = Field(
        default="10.43.0.0/16",
        env="RKE2_SERVICE_CIDR",
        description="Kubernetes service IP range"
    )
    pod_cidr: str = Field(
        default="10.42.0.0/16",
        env="RKE2_POD_CIDR",
        description="Kubernetes pod IP range"
    )
    cluster_dns: str = Field(
        default="10.43.0.10",
        env="RKE2_CLUSTER_DNS",
        description="Cluster DNS server IP"
    )

class InstallerConfig(BaseModel):
    """RKE2 installer configuration."""
    ssh: SSHConfig = Field(default_factory=SSHConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    cluster: ClusterConfig = Field(default_factory=ClusterConfig)
    config_paths: List[Path] = Field(
        default_factory=lambda: list(DEFAULT_CONFIG_PATHS),
        exclude=True  # Don't include in serialization
    )

    class Config:
        env_prefix = "RKE2_"
        env_nested_delimiter = "__"
        extra = "ignore"

    @classmethod
    def load(cls, config_path: Optional[Union[str, Path]] = None) -> 'InstallerConfig':
        """Load configuration from file and environment variables."""
        config_data: Dict[str, Any] = {}
        
        # Try to load from explicit path if provided
        if config_path:
            config_path = Path(config_path).expanduser().absolute()
            if config_path.exists():
                config_data = cls._load_config_file(config_path)
        else:
            # Try default paths
            for path in DEFAULT_CONFIG_PATHS:
                path = path.expanduser().absolute()
                if path.exists():
                    config_data = cls._load_config_file(path)
                    break
        
        # Load from environment variables and apply overrides
        return cls(**config_data)

    @classmethod
    def _load_config_file(cls, path: Path) -> Dict[str, Any]:
        """Load configuration from a YAML file."""
        try:
            with open(path, 'r') as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            logger.warning(f"Failed to load config from {path}: {e}")
            return {}

    def save(self, path: Union[str, Path]) -> None:
        """Save configuration to a file."""
        path = Path(path).expanduser().absolute()
        path.parent.mkdir(parents=True, exist_ok=True)
        
        # Convert to dict and remove excluded fields
        config_dict = self.dict(exclude={"config_paths"}, exclude_none=True)
        
        with open(path, 'w') as f:
            yaml.safe_dump(config_dict, f, default_flow_style=False, sort_keys=False)

# Global configuration instance
_config: Optional[InstallerConfig] = None

def get_config(config_path: Optional[Union[str, Path]] = None) -> InstallerConfig:
    """Get or create the global configuration instance."""
    global _config
    if _config is None:
        _config = InstallerConfig.load(config_path)
    return _config

def set_config(config: InstallerConfig) -> None:
    """Set the global configuration instance."""
    global _config
    _config = config
