"""
Data models for RKE2 cluster management.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
import time

@dataclass
class Node:
    """Represents a node in the cluster."""
    name: str
    ip: str
    role: str  # 'master' or 'worker'
    ssh_user: str = 'ubuntu'
    ssh_key_path: str = '~/.ssh/id_rsa'
    labels: Dict[str, str] = field(default_factory=dict)
    taints: List[Dict[str, str]] = field(default_factory=list)

@dataclass
class NodeMetrics:
    """Tracks metrics for node operations."""
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None
    operations: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    errors: List[Dict[str, Any]] = field(default_factory=list)

    def record_operation(self, name: str, duration: float, success: bool, **kwargs):
        """Record an operation with its metrics."""
        self.operations[name] = {
            'duration': duration,
            'success': success,
            'timestamp': time.time(),
            **kwargs
        }
        if not success:
            self.errors.append({
                'operation': name,
                'timestamp': time.time(),
                **kwargs
            })

@dataclass
class DeploymentState:
    """Tracks the state of a cluster deployment."""
    phase: str = 'not_started'
    nodes_processed: int = 0
    nodes_failed: int = 0
    current_batch: int = 0
    total_batches: int = 0
    start_time: float = field(default_factory=time.time)
    metrics: Dict[str, Any] = field(default_factory=dict)

    def update_phase(self, phase: str):
        """Update the current deployment phase."""
        self.phase = phase
        self.metrics[f'phase_{phase}_start'] = time.time()

    def record_batch_completion(self, success_count: int, failed_count: int):
        """Record completion of a batch of nodes."""
        self.nodes_processed += success_count
        self.nodes_failed += failed_count
        self.current_batch += 1
