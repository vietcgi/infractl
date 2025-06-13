"""RKE2 installation and management.

This module provides a high-level interface for RKE2 cluster deployment and management.
It's recommended to use the functions and classes from the `rke2.installer` package
instead of importing directly from this module.
"""

import logging

from .installer.core import RKE2Installer
from .installer.deployment import deploy_cluster

logger = logging.getLogger("rke2.installer")

# Re-export the main classes and functions
__all__ = ['RKE2Installer', 'deploy_cluster']
