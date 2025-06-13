"""RKE2 reset functionality."""
import concurrent.futures
import logging
import os
import shlex
import subprocess
from typing import List, Optional, Tuple, Union

from infractl.modules.ssh import ConnectionPool
from .models import Node

logger = logging.getLogger(__name__)

class RKE2Reset:
    """Handles RKE2 reset operations."""
    
    def __init__(self, connection_pool: ConnectionPool):
        """Initialize the RKE2 reset handler.
        
        Args:
            connection_pool: Connection pool for SSH connections
        """
        self.connection_pool = connection_pool
    
    def _run_script(self, node: Node, script_name: str) -> Tuple[bool, str]:
        """Run an RKE2 script on the remote node.
        
        Args:
            node: The node to run the script on
            script_name: Name of the script to run (e.g., 'rke2-killall.sh')
            
        Returns:
            Tuple[bool, str]: (success, message)
        """
        script_path = f"/usr/local/bin/{script_name}"
        logger.info(f"Running {script_path} on {node.name}")
        
        try:
            # Build SSH command
            ssh_cmd = [
                'ssh',
                '-o', 'StrictHostKeyChecking=no',
                '-o', 'UserKnownHostsFile=/dev/null',
                '-o', 'LogLevel=ERROR',
                '-o', 'ConnectTimeout=10',
                '-o', 'BatchMode=yes',
                '-i', node.ssh_key_path,
                f'{node.ssh_user}@{node.ip}',
                f'sudo {script_path} 2>&1'
            ]
            
            # Execute command
            result = subprocess.run(
                ssh_cmd,
                capture_output=True,
                text=True,
                timeout=300  # 5 minute timeout
            )
            
            if result.returncode == 0:
                return True, f"Successfully ran {script_name}"
            
            error_msg = result.stderr or result.stdout or "Unknown error"
            return False, f"Failed to run {script_name}: {error_msg}"
            
        except subprocess.TimeoutExpired:
            return False, f"Timeout while running {script_name}"
        except Exception as e:
            return False, f"Error running {script_name}: {str(e)}"
    
    def reset_node(self, node: Node, is_server: bool = True, reinstall: bool = False) -> bool:
        """Reset RKE2 on a single node by running the killall and uninstall scripts.
        
        Args:
            node: The node to reset
            is_server: Whether this is a server node (kept for backward compatibility)
            reinstall: Kept for backward compatibility, not used
            
        Returns:
            bool: True if reset was successful, False otherwise
        """
        logger.info(f"Starting RKE2 reset on {node.name}")
        
        # Step 1: Run rke2-killall.sh
        success, message = self._run_script(node, 'rke2-killall.sh')
        if not success:
            logger.warning(f"Warning: {message}")
        
        # Step 2: Run rke2-uninstall.sh
        success, message = self._run_script(node, 'rke2-uninstall.sh')
        if not success:
            logger.warning(f"Warning: {message}")
        
        logger.info(f"Completed RKE2 reset on {node.name}")
        return True


def _reset_single_node(connection_pool: ConnectionPool, node: Node, is_server: bool, reinstall: bool) -> Tuple[Node, Union[bool, Exception]]:
    """Helper function to reset a single node, used for parallel execution."""
    try:
        reset_handler = RKE2Reset(connection_pool)
        result = reset_handler.reset_node(node, is_server=is_server, reinstall=reinstall)
        return node, result
    except Exception as e:
        return node, e

def reset_rke2_node(
    connection_pool: ConnectionPool,
    node: Union[Node, List[Node]],
    is_server: bool = True,
    reinstall: bool = False,
    max_workers: Optional[int] = None
) -> Union[bool, List[Tuple[Node, Union[bool, Exception]]]]:
    """Reset one or more RKE2 nodes in parallel.
    
    Args:
        connection_pool: Connection pool for SSH connections
        node: Single node or list of nodes to reset
        is_server: Whether these are server nodes
        reinstall: Whether to reinstall RKE2 after cleanup (kept for backward compatibility)
        max_workers: Maximum number of parallel workers (default: min(32, os.cpu_count() + 4))
        
    Returns:
        - If a single node was provided: bool indicating success
        - If multiple nodes: List of tuples (node, result) where result is either:
          - True: Success
          - Exception: The exception that was raised
    """
    if isinstance(node, list):
        if not node:
            return []
            
        # Process multiple nodes in parallel
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(_reset_single_node, connection_pool, n, is_server, reinstall): n
                for n in node
            }
            
            results = []
            for future in concurrent.futures.as_completed(futures):
                node = futures[future]
                try:
                    result = future.result()
                    results.append(result)
                except Exception as e:
                    results.append((node, e))
            
            return results
    else:
        # Single node case
        try:
            reset_handler = RKE2Reset(connection_pool)
            return reset_handler.reset_node(node, is_server=is_server, reinstall=reinstall)
        except Exception as e:
            logger.error(f"Error in reset_rke2_node for {node.name}: {e}", exc_info=True)
            raise
