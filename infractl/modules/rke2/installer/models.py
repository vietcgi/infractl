"""Data models for the RKE2 installer."""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from enum import Enum, auto


class NodeRole(str, Enum):
    """Node roles in the RKE2 cluster."""
    MASTER = 'master'
    WORKER = 'worker'


class DeploymentPhase(str, Enum):
    """Phases of the cluster deployment process."""
    NOT_STARTED = 'not_started'
    DEPLOYING_MASTERS = 'deploying_masters'
    DEPLOYING_WORKERS = 'deploying_workers'
    COMPLETED = 'completed'
    FAILED = 'failed'


@dataclass
class Node:
    """Represents a node in the RKE2 cluster."""
    name: str
    ip: str
    role: NodeRole
    internal_ip: Optional[str] = None
    hostname_override: Optional[str] = None
    labels: Dict[str, str] = field(default_factory=dict)
    taints: List[Dict[str, str]] = field(default_factory=list)
    user: str = 'root'
    port: int = 22
    ssh_key_path: Optional[str] = None


@dataclass
class DeploymentState:
    """Tracks the state of a cluster deployment."""
    phase: DeploymentPhase = DeploymentPhase.NOT_STARTED
    current_batch: int = 0
    total_batches: int = 0
    nodes_completed: int = 0
    total_nodes: int = 0
    errors: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def update_phase(self, phase: DeploymentPhase) -> None:
        """Update the deployment phase."""
        self.phase = phase

    def add_error(self, error: str) -> None:
        """Add an error message to the deployment state."""
        self.errors.append(error)


@dataclass
class ClusterConfig:
    """Configuration for an RKE2 cluster."""
    cluster_name: str
    cluster_domain: str = 'cluster.local'
    service_cidr: str = '10.43.0.0/16'
    pod_cidr: str = '10.42.0.0/16'
    cluster_dns: str = '10.43.0.10'
    cluster_dns_search: List[str] = field(default_factory=lambda: ['svc.cluster.local'])
    disable_network_policy: bool = False
    tls_san: List[str] = field(default_factory=list)
    node_taints: List[Dict[str, str]] = field(default_factory=list)
    node_labels: Dict[str, str] = field(default_factory=dict)
    kubelet_args: List[str] = field(default_factory=list)
    kube_apiserver_args: List[str] = field(default_factory=list)
    kube_controller_manager_args: List[str] = field(default_factory=list)
    kube_scheduler_args: List[str] = field(default_factory=list)
    kube_proxy_args: List[str] = field(default_factory=list)
    etcd_args: List[str] = field(default_factory=list)
    kubelet_path: str = '/var/lib/rancher/rke2/bin/kubelet'
    kube_apiserver_path: str = '/var/lib/rancher/rke2/bin/kube-apiserver'
    kube_controller_manager_path: str = '/var/lib/rancher/rke2/bin/kube-controller-manager'
    kube_scheduler_path: str = '/var/lib/rancher/rke2/bin/kube-scheduler'
    kube_proxy_path: str = '/var/lib/rancher/rke2/bin/kube-proxy'
    etcd_bin_path: str = '/var/lib/rancher/rke2/bin/etcd'
    etcd_data_dir: str = '/var/lib/rancher/rke2/server/db/etcd'
