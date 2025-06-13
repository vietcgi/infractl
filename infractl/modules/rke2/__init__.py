"""
RKE2 Cluster Management Module

This package provides functionality for deploying and managing RKE2 clusters at scale.

Key Features:
- Automated deployment of RKE2 clusters
- Support for both single-node and HA control planes
- Worker node scaling
- Cluster health monitoring
- Connection pooling for efficient SSH operations
- Cluster reset and cleanup utilities
- Modular installer with clean separation of concerns
- Flexible configuration management with environment variable overrides
"""

import logging
import os
from pathlib import Path
from typing import Optional

# Core functionality
from .models import Node, NodeMetrics, DeploymentState
from .deploy import ClusterDeployment
from .reset import RKE2Reset, reset_rke2_node
from .health import wait_for_control_plane_ready, check_cluster_health
from .installer import RKE2Installer

# Configuration management
from .config import InstallerConfig, get_config, set_config, DEFAULT_CONFIG_PATHS
from .configure import create_config_file, validate_config_file, show_config

__all__ = [
    # Core classes
    'Node',
    'NodeMetrics',
    'DeploymentState',
    'ClusterDeployment',
    'RKE2Reset',
    'RKE2Installer',
    
    # Configuration management
    'InstallerConfig',
    'get_config',
    'set_config',
    'create_config_file',
    'validate_config_file',
    'show_config',
    
    # Cluster operations
    'reset_rke2_node',
    'wait_for_control_plane_ready',
    'check_cluster_health',
]

__version__ = "0.2.0"

# Set up logging when module is imported
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Configure logging based on configuration
try:
    config = get_config()
    logger = logging.getLogger(__name__)
    
    # Set log level from config
    log_level = getattr(logging, config.logging.level.upper(), logging.INFO)
    logging.getLogger("rke2").setLevel(log_level)
    
    # Configure file logging if specified
    if config.logging.file:
        from logging.handlers import RotatingFileHandler
        
        log_file = Path(config.logging.file).expanduser().absolute()
        log_file.parent.mkdir(parents=True, exist_ok=True)
        
        file_handler = RotatingFileHandler(
            filename=log_file,
            maxBytes=config.logging.max_size_mb * 1024 * 1024,
            backupCount=config.logging.backup_count
        )
        
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        file_handler.setFormatter(formatter)
        
        logging.getLogger("rke2").addHandler(file_handler)
        logger.debug(f"Logging to file: {log_file}")
    
    # Log the configuration source
    loaded_from = next((str(p) for p in DEFAULT_CONFIG_PATHS if p.expanduser().exists()), "default values")
    logger.debug(f"RKE2 module initialized with config from: {loaded_from}")
    
except Exception as e:
    # If there's an error loading the config, just use basic logging
    logging.warning(f"Could not initialize RKE2 configuration: {e}")
    logging.warning("Using default logging configuration")
