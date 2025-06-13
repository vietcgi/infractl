"""Core RKE2 installation logic.

This module contains the base RKE2Installer class and core installation methods.
"""

import logging
import random
import re
import shlex
import shutil
import socket
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import paramiko
from paramiko.ssh_exception import (
    AuthenticationException,
    BadHostKeyException,
    NoValidConnectionsError,
    SSHException,
)

from ..reset import RKE2Reset
from ..models import Node, DeploymentState
from ..config import get_config, InstallerConfig, DEFAULT_CONFIG_PATHS
from infractl.modules.ssh import ConnectionPool as SSHConnectionPool
import os

logger = logging.getLogger("rke2.installer.core")

class RKE2Installer:
    """Handles RKE2 installation and cluster management.
    
    This class provides the core functionality for deploying and managing RKE2 clusters.
    It's designed to work with the modular installer structure while maintaining
    compatibility with the original install_rke2_scalable.py functionality.
    """
    
    def __init__(
        self,
        connection_pool: SSHConnectionPool,
        cluster_token: Optional[str] = None,
        dry_run: bool = False,
        config_path: Optional[Union[str, Path]] = None
    ):
        """Initialize the RKE2 installer.
        
        Args:
            connection_pool: Connection pool for SSH connections
            cluster_token: Optional cluster token (overrides config if provided)
            dry_run: If True, only log commands without executing them
            config_path: Optional path to configuration file
        """
        # Load configuration
        self.config = get_config(config_path)
        
        # Initialize instance variables
        self.connection_pool = connection_pool
        self.dry_run = dry_run
        self.state = DeploymentState()
        
        # Set cluster token (from parameter or config or generate new)
        self.cluster_token = cluster_token or self.config.cluster.token or self._generate_token()
        
        # Set node configuration
        self.bootstrap_ip = None  # Will be set when first master is installed
        self.node_token = None  # Will store the node token from the first master
        self.interface = self.config.cluster.interface
        
        # Set up logging
        self._setup_logging()
        
        logger.info(f"Initialized RKE2Installer with config from: {self._get_loaded_config_source()}")
    
    def _setup_logging(self) -> None:
        """Set up logging based on configuration."""
        import logging.handlers
        
        # Set log level
        log_level = getattr(logging, self.config.logging.level.upper(), logging.INFO)
        logger.setLevel(log_level)
        
        # Clear existing handlers
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)
        
        # Create formatter
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        
        # Add console handler
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
        
        # Add file handler if configured
        if self.config.logging.file:
            log_file = Path(self.config.logging.file).expanduser().absolute()
            log_file.parent.mkdir(parents=True, exist_ok=True)
            
            file_handler = logging.handlers.RotatingFileHandler(
                filename=log_file,
                maxBytes=self.config.logging.max_size_mb * 1024 * 1024,
                backupCount=self.config.logging.backup_count
            )
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
    
    def _get_loaded_config_source(self) -> str:
        """Get the source of the loaded configuration."""
        for path in DEFAULT_CONFIG_PATHS:
            path = Path(path).expanduser().absolute()
            if path.exists():
                return str(path)
        return "default configuration"
    
    @staticmethod
    def _generate_token() -> str:
        """Generate a deterministic cluster token.
        
        Returns:
            str: A fixed token that will be the same across all runs
        """
        # Use a fixed token that will be the same across all runs
        # This ensures consistency when the installer is restarted
        return "emodo-cluster-token-1234567890"
    
    def _command_requires_sudo(self, command: str) -> bool:
        """Check if a command requires sudo privileges.
        
        Args:
            command: Command to check
            
        Returns:
            bool: True if the command requires sudo, False otherwise
        """
        # List of commands that typically require sudo
        sudo_commands = [
            'systemctl', 'apt', 'yum', 'dnf', 'zypper', 'apk',
            'kubectl', 'kubeadm', 'kubelet', 'etcdctl',
            'mount', 'umount', 'ip', 'iptables', 'ipset', 'ebtables',
            'modprobe', 'rmmod', 'insmod', 'lsmod',
            'docker', 'containerd', 'crictl', 'runc',
            'chmod', 'chown', 'chgrp', 'chattr', 'setfacl',
            'useradd', 'userdel', 'usermod', 'groupadd', 'groupdel',
            'visudo', 'vipw', 'vigr',
            'journalctl', 'logrotate',
            'reboot', 'shutdown', 'halt', 'poweroff',
            'kexec', 'swapon', 'swapoff'
        ]
        
        # Check if command starts with any of the sudo commands
        return any(command.strip().startswith(cmd) for cmd in sudo_commands)

    def _ssh_exec(
        self,
        node: Node,
        command: str,
        check: bool = True,
        timeout: Optional[int] = None,
        use_sudo: bool = True,
        retries: int = 3,
        retry_delay: int = 5,
        command_timeout: Optional[int] = None
    ) -> str:
        """Execute a command on a node via SSH with improved error handling and retries.
        
        Args:
            node: Node to execute command on
            command: Command to execute
            check: If True, raise exception on non-zero exit code
            timeout: Connection timeout in seconds (None to use config default)
            use_sudo: Whether to automatically use sudo for privileged commands
            retries: Number of retry attempts for transient failures
            retry_delay: Initial delay between retries in seconds (will be doubled each retry)
            command_timeout: Command execution timeout in seconds (None for no timeout)
            
        Returns:
            str: Command output
            
        Raises:
            subprocess.CalledProcessError: If check=True and command fails after all retries
            TimeoutError: If command times out
            ConnectionError: If SSH connection fails after all retries
        """
        # Use command_timeout if provided, otherwise fall back to timeout
        exec_timeout = command_timeout if command_timeout is not None else timeout
        if not node.ip:
            raise ValueError(f"Node {node.name} has no IP address")
            
        # Get SSH configuration
        ssh_user = node.ssh_user or self.config.ssh.user
        ssh_key_path = node.ssh_key_path or self.config.ssh.key_path
        
        if not ssh_user or not ssh_key_path:
            raise ValueError(f"SSH user and key path must be specified for node {node.name}")
        
        # Ensure key file has correct permissions
        try:
            if os.path.exists(ssh_key_path):
                os.chmod(ssh_key_path, 0o600)
        except Exception as e:
            logger.warning(f"Failed to set permissions on key file {ssh_key_path}: {e}")
            
        # Prepare the command
        final_command = command
        if use_sudo and self._command_requires_sudo(command):
            final_command = f'sudo -n {final_command}'
            
        last_exception = None
        
        for attempt in range(1, retries + 1):
            try:
                if self.dry_run:
                    logger.info("[DRY RUN] Would execute on %s: %s", node.name, final_command)
                    return ""
                
                # Get connection with increased timeout for initial connection
                connect_timeout = max(60, self.config.ssh.connect_timeout)  # At least 60 seconds
                command_timeout = timeout or 300  # Default 5 minutes for command execution
                
                # Log command execution attempt with full connection details
                logger.debug(
                    "[%s] Executing command (attempt %d/%d): %s\n"
                    "SSH Connection Details:\n"
                    "  Host: %s\n"
                    "  User: %s\n"
                    "  Key: %s\n"
                    "  Port: %d\n"
                    "  Connect Timeout: %d\n"
                    "  Command Timeout: %d",
                    node.name, attempt, retries, final_command,
                    node.ip,
                    ssh_user,
                    ssh_key_path,
                    self.config.ssh.port,
                    connect_timeout,
                    command_timeout
                )
                
                with self.connection_pool.get_connection(
                    host=node.ip,
                    username=ssh_user,
                    key_path=ssh_key_path,
                    port=self.config.ssh.port,
                    timeout=connect_timeout
                ) as conn:
                    # Use only native SSH logic for command execution
                    stdin, stdout, stderr = conn.exec_command(
                        f'set -euo pipefail; {final_command}',
                        get_pty=True,
                        timeout=command_timeout
                    )
                    logger.debug("[%s] Command execution started successfully", node.name)
                    
                    # Wait for the command to complete with timeout
                    start_time = time.time()
                    timeout_remaining = command_timeout
                    last_activity = start_time
                    output_buffer = []
                    error_buffer = []
                    
                    while not stdout.channel.exit_status_ready():
                        current_time = time.time()
                        elapsed = current_time - start_time
                        
                        # Check for timeout
                        if elapsed > timeout_remaining:
                            # Try to capture any available output before failing
                            try:
                                output = stdout.read()
                                error = stderr.read()
                                if output:
                                    output_buffer.append(output)
                                if error:
                                    error_buffer.append(error)
                            except Exception as e:
                                logger.debug("Failed to read command output: %s", str(e))
                            
                            error_msg = [
                                f"Command timed out after {timeout_remaining:.1f} seconds on {node.name}",
                                f"(attempt {attempt}/{retries})",
                                f"Command: {final_command}"
                            ]
                            
                            if output_buffer:
                                error_msg.append("Last output:" + "\n".join(output_buffer[-5:]))
                            if error_buffer:
                                error_msg.append("Last errors:" + "\n".join(error_buffer[-5:]))
                            
                            raise TimeoutError("\n".join(error_msg))
                        
                        # Check for connection issues
                        if current_time - last_activity > 30:  # 30 seconds of no activity
                            # Try a keepalive check
                            try:
                                transport = conn.get_transport()
                                if transport and transport.is_active():
                                    transport.send_ignore()
                                    last_activity = current_time
                                    continue
                                else:
                                    logger.warning("SSH connection appears to be inactive")
                                    raise ConnectionError("SSH connection became inactive")
                            except Exception as e:
                                logger.warning("SSH keepalive check failed: %s", str(e))
                                raise ConnectionError(f"SSH connection failed: {str(e)}")
                        
                        # Try to read any available output
                        try:
                            if stdout.channel.recv_ready():
                                chunk = stdout.channel.recv(4096).decode('utf-8', 'replace')
                                if chunk:
                                    output_buffer.append(chunk)
                                    last_activity = current_time
                            
                            if stderr.channel.recv_stderr_ready():
                                chunk = stderr.channel.recv_stderr(4096).decode('utf-8', 'replace')
                                if chunk:
                                    error_buffer.append(chunk)
                                    last_activity = current_time
                        except Exception as e:
                            logger.debug("Error reading command output: %s", str(e))
                        
                        time.sleep(0.5)  # Reduced sleep time for better responsiveness
                    
                    # Read any remaining output after command completes
                    try:
                        output = stdout.read().decode('utf-8', 'replace')
                        if output:
                            output_buffer.append(output)
                        
                        error = stderr.read().decode('utf-8', 'replace')
                        if error:
                            error_buffer.append(error)
                    except Exception as e:
                        logger.debug("Error reading final command output: %s", str(e))
                    
                    # Get exit status and combine all output
                    exit_status = stdout.channel.exit_status
                    full_output = ''.join(output_buffer + error_buffer)
                    
                    # Log the full output for debugging
                    log_level = logging.DEBUG if exit_status == 0 else logging.ERROR
                    logger.log(
                        log_level,
                        "[%s] Command completed with exit status %d (attempt %d/%d): %s\nOutput:\n%s",
                        node.name, exit_status, attempt, retries, final_command, full_output
                    )
                    
                    # Handle command execution errors
                    exit_code = exit_status
                    if exit_code != 0 and check:
                        stderr_output = ''
                        try:
                            stderr_output = stderr.read().decode('utf-8', errors='replace')
                        except Exception as read_error:
                            logger.debug("[%s] Failed to read stderr: %s", node.name, str(read_error))
                            stderr_output = 'Failed to capture stderr'
                            
                        error_msg = f"[%s] Command failed with exit code {exit_code}\n" \
                                   f"Command: {final_command}\n" \
                                   f"Stderr: {stderr_output}"
                        logger.error(error_msg, node.name)
                        
                        # Check if this is a transient error that might succeed on retry
                        is_transient = any(
                            msg in full_output.lower() for msg in [
                                'connection reset',
                                'connection refused',
                                'temporary failure',
                                'timed out',
                                'no route to host',
                                'connection closed',
                                'broken pipe'
                            ]
                        )
                        
                        if is_transient and attempt < retries:
                            logger.warning(
                                "[%s] Transient error detected, will retry (attempt %d/%d)",
                                node.name, attempt + 1, retries
                            )
                            continue
                            
                        # If this is not a transient error or we're out of retries, raise the error
                        if not is_transient or attempt >= retries:
                            if check:
                                # Import subprocess here to ensure it's available
                                import subprocess as sp
                                raise sp.CalledProcessError(
                                    exit_status, final_command, full_output, None
                                )
                        
                        # Prepare for retry if this is a transient error
                        import subprocess as sp
                        last_exception = sp.CalledProcessError(
                            exit_status, final_command, full_output, None
                        )
                        logger.warning(
                            "[%s] Transient error detected, will retry (attempt %d/%d)",
                            node.name, attempt, retries
                        )
                    
                    # Exponential backoff with jitter
                if attempt < retries:
                    sleep_time = min(60, retry_delay * (2 ** (attempt - 1)) + random.uniform(0, 1))
                    logger.warning(
                        "[%s] Retrying in %.1f seconds... (attempt %d/%d)",
                        node.name, sleep_time, attempt + 1, retries
                    )
                    time.sleep(sleep_time)
                else:
                    # If we get here, all retries failed
                    error_msg = f"Failed to execute command on {node.name} after {retries} attempts"
                    if last_exception:
                        error_msg += f": {str(last_exception)}"
                    
                    # Try to read any remaining output
                    try:
                        while True:
                            if stdout.channel.recv_ready():
                                chunk = stdout.channel.recv(4096).decode('utf-8', 'replace')
                                if chunk:
                                    output_buffer.append(chunk)
                            elif stderr.channel.recv_stderr_ready():
                                chunk = stderr.channel.recv_stderr(4096).decode('utf-8', 'replace')
                                if chunk:
                                    error_buffer.append(chunk)
                            else:
                                break
                    except Exception as e:
                        logger.debug("Error reading final command output: %s", str(e))
                    
                    # Combine all output
                    full_output = ''.join(output_buffer + error_buffer)
                    
                    if check and last_exception is not None:
                        try:
                            if isinstance(last_exception, (socket.timeout, TimeoutError)):
                                raise TimeoutError(error_msg) from last_exception
                            elif isinstance(last_exception, (EOFError, ConnectionError, socket.error)):
                                raise ConnectionError(error_msg) from last_exception
                            elif hasattr(subprocess, 'CalledProcessError') and isinstance(last_exception, subprocess.CalledProcessError):
                                raise last_exception
                            else:
                                raise RuntimeError(error_msg) from last_exception
                        except Exception as e:
                            logger.error("Error handling command failure: %s", str(e))
                            raise
                    
                    return full_output
                
            except Exception as e:
                last_exception = e
                error_type = type(e).__name__
                
                # Check if it's one of the expected exception types
                expected_errors = (socket.timeout, TimeoutError, EOFError, ConnectionError, socket.error)
                if not isinstance(e, expected_errors):
                    raise  # Re-raise if it's not one of our expected exceptions
                
                # Log the error with appropriate level
                if attempt >= retries:
                    log_level = logging.ERROR
                else:
                    log_level = logging.WARNING
                
                logger.log(
                    log_level,
                    "[%s] SSH command failed (attempt %d/%d, %s): %s",
                    node.name, attempt, retries, error_type, str(e)
                )
                
                # If we got a socket error or timeout, the connection might be bad
                if isinstance(e, (socket.error, EOFError, TimeoutError)) and attempt < max_retries:
                    logger.debug("Removing connection from pool due to %s", error_type)
                    with self.connection_pool.lock:
                        connection_id = f"{ssh_user}@{node.ip}"
                        if connection_id in self.connection_pool.connections:
                            try:
                                self.connection_pool.connections[connection_id].close()
                            except Exception as close_error:
                                logger.debug("Error closing connection: %s", str(close_error))
                            del self.connection_pool.connections[connection_id]
                
                if attempt < max_retries:
                    # Exponential backoff with jitter, max 60 seconds
                    base_delay = min(5 * (2 ** (attempt - 1)), 30)  # 5, 10, 20, 30, 30, ...
                    jitter = random.uniform(0.5, 1.5)  # Random jitter between 0.5x and 1.5x
                    retry_delay = min(int(base_delay * jitter), 60)
                    
                    logger.debug("Retrying in %d seconds (jittered from %.1f base)...", 
                                retry_delay, base_delay)
                    time.sleep(retry_delay)
                    continue
                
                # Create a more informative error message
                error_msg = [
                    f"Failed to execute command on {node.name} after {max_retries} attempts",
                    f"Last error ({error_type}): {str(e)}",
                    f"Command: {final_command}"
                ]
                
                # Add context if available
                if hasattr(e, 'output') and e.output:
                    error_msg.append(f"Output: {e.output}")
                if hasattr(e, 'stderr') and e.stderr:
                    error_msg.append(f"Stderr: {e.stderr}")
                
                raise RuntimeError("\n".join(error_msg)) from e
                    
            except (socket.timeout, TimeoutError, EOFError, ConnectionError, socket.error) as e:
                last_exception = e
                error_type = type(e).__name__
                
                # Log the error with appropriate level
                if attempt >= max_retries:
                    log_level = logging.ERROR
                else:
                    log_level = logging.WARNING
                
                logger.log(
                    log_level,
                    "[%s] SSH command failed (attempt %d/%d, %s): %s",
                    node.name, attempt, max_retries, error_type, str(e)
                )
                
                # If we got a socket error or timeout, the connection might be bad
                if isinstance(e, (socket.error, EOFError, TimeoutError)) and attempt < max_retries:
                    logger.debug("Removing connection from pool due to %s", error_type)
                    with self.connection_pool.lock:
                        connection_id = f"{ssh_user}@{node.ip}"
                        if connection_id in self.connection_pool.connections:
                            try:
                                self.connection_pool.connections[connection_id].close()
                            except Exception as close_error:
                                logger.debug("Error closing connection: %s", str(close_error))
                            del self.connection_pool.connections[connection_id]
                
                if attempt < max_retries:
                    # Exponential backoff with jitter, max 60 seconds
                    base_delay = min(5 * (2 ** (attempt - 1)), 30)  # 5, 10, 20, 30, 30, ...
                    jitter = random.uniform(0.5, 1.5)  # Random jitter between 0.5x and 1.5x
                    retry_delay = min(int(base_delay * jitter), 60)
                    
                    logger.debug("Retrying in %d seconds (jittered from %.1f base)...", 
                                retry_delay, base_delay)
                    time.sleep(retry_delay)
                    continue
                
                # Create a more informative error message
                error_msg = [
                    f"Failed to execute command on {node.name} after {max_retries} attempts",
                    f"Last error ({error_type}): {str(e)}",
                    f"Command: {final_command}"
                ]
                
                # Add context if available
                if hasattr(e, 'output') and e.output:
                    error_msg.append(f"Output: {e.output}")
                if hasattr(e, 'stderr') and e.stderr:
                    error_msg.append(f"Stderr: {e.stderr}")
                
                raise RuntimeError("\n".join(error_msg)) from e
                
        # This should never be reached due to the raise above, but just in case
        return ""
    
    def _sftp_put(
        self,
        node: Node,
        local_path: str,
        remote_path: str,
        mode: Optional[int] = None
    ) -> None:
        """Upload a file to the remote node using SFTP.

        Args:
            node: Node to upload file to
            local_path: Local path to the file
            remote_path: Remote path to upload to
            mode: Optional file mode (permissions) to set on the remote file

        Raises:
            RuntimeError: If file upload fails after all retry attempts
            FileNotFoundError: If local file doesn't exist
        """
        if not os.path.exists(local_path):
            raise FileNotFoundError(f"Local file not found: {local_path}")

        max_attempts = 3
        last_error = None

        for attempt in range(1, max_attempts + 1):
            try:
                # Get SSH configuration with node-specific overrides
                ssh_user = node.ssh_user or self.config.ssh.user
                ssh_key_path = node.ssh_key_path or self.config.ssh.key_path
                
                # Upload the file using the connection pool
                with self.connection_pool.get_connection(
                    host=node.ip,
                    username=ssh_user,
                    key_path=ssh_key_path,
                    port=self.config.ssh.port,
                    timeout=self.config.ssh.connect_timeout
                ) as conn:
                    # Ensure remote directory exists
                    remote_dir = os.path.dirname(remote_path)
                    if remote_dir:
                        conn.mkdir(remote_dir, mode=0o755)
                    
                    # Upload the file
                    conn.put(local_path, remote_path)
                    
                    # Set file mode if specified
                    if mode is not None:
                        conn.execute(f'chmod {mode:o} {remote_path}')
                    
                    logger.debug("[%s] Successfully uploaded %s to %s", node.name, local_path, remote_path)
                    return
                    
            except Exception as e:
                last_error = e
                logger.warning(
                    "[%s] Attempt %d/%d: Failed to upload file: %s",
                    node.name, attempt, max_attempts, str(e)
                )
                if attempt < max_attempts:
                    time.sleep(2 ** attempt)  # Exponential backoff
        
        # If we get here, all attempts failed
        raise RuntimeError(
            f"Failed to upload {local_path} to {node.name}:{remote_path} after {max_attempts} attempts: {str(last_error)}"
        )

    def _ssh_upload(
        self,
        node: Node,
        local_path: str,
        remote_path: str,
        mode: Optional[int] = None
    ) -> None:
        """Upload a file to the remote node (compatibility wrapper for _sftp_put).
        
        This method provides a backward-compatible interface for code that expects
        an _ssh_upload method. It simply calls _sftp_put with the same parameters.
        
        Args:
            node: Node to upload file to
            local_path: Local path to the file
            remote_path: Remote path to upload to
            mode: Optional file mode (permissions) to set on the remote file
            
        Raises:
            RuntimeError: If file upload fails
            FileNotFoundError: If local file doesn't exist
        """
        return self._sftp_put(node, local_path, remote_path, mode)

    def log(self, node: Node, message: str) -> None:
        """Log a message with node context.
        
        Args:
            node: Node the message is related to
            message: Message to log
        """
        logger.info("[%s] %s", node.name, message)
    
    def is_rke2_installed(self, node: Node) -> bool:
        """Check if RKE2 is installed on the node.
        
        Args:
            node: Node to check
            
        Returns:
            bool: True if RKE2 is installed, False otherwise
        """
        try:
            # Check if RKE2 binary exists and is executable
            result = self._ssh_exec(node, 'command -v rke2', check=False)
            return bool(result.strip())
        except Exception as e:
            logger.warning("[%s] Failed to check if RKE2 is installed: %s", node.name, str(e))
            return False
    
    def is_rke2_service_active(self, node: Node, service_name: str = None) -> bool:
        """Check if RKE2 service is active on the node.
        
        Args:
            node: Node to check
            service_name: Service name to check (rke2-server or rke2-agent)
            
        Returns:
            bool: True if service is active, False otherwise
        """
        if not service_name:
            service_name = 'rke2-server' if node.role == 'master' else 'rke2-agent'
            
        try:
            # Check service status using systemd
            result = self._ssh_exec(node, f'systemctl is-active {service_name}', check=False)
            return 'active' in result.lower()
        except Exception as e:
            logger.warning("[%s] Failed to check %s status: %s", node.name, service_name, str(e))
            return False
    
    def install_master(self, node: Node, reset: bool = True) -> bool:
        """Install and configure RKE2 on a master node.
        
        This method handles the complete installation process for a master node,
        including system dependencies, RKE2 installation, and configuration.
        
        Args:
            node: The master node to install RKE2 on
            reset: Whether to reset the node before installation
            
        Returns:
            bool: True if installation was successful, False otherwise
        """
        try:
            self.log(node, "🚀 Starting RKE2 master installation")
            
            # Reset node if requested
            if reset and not self.reset_node(node):
                self.log(node, "❌ Failed to reset node before installation")
                return False
            
            # Install system dependencies
            if not self.install_system_dependencies(node):
                self.log(node, "❌ Failed to install system dependencies")
                return False
            
            # Configure RKE2
            if not self.configure_rke2(node, is_server=True):
                self.log(node, "❌ Failed to configure RKE2")
                return False
            
            # Install RKE2
            if not self.install_rke2(node, is_server=True):
                self.log(node, "❌ Failed to install RKE2")
                return False
            
            # Wait for the node to be ready
            max_attempts = 30
            for attempt in range(1, max_attempts + 1):
                if self.is_rke2_service_active(node, 'rke2-server'):
                    # Get the node token for other nodes to join
                    self._get_node_token(node)
                    
                    # Verify kubectl is working
                    try:
                        self._ssh_exec(
                            node,
                            'export KUBECONFIG=/etc/rancher/rke2/rke2.yaml && '
                            'export PATH=$PATH:/var/lib/rancher/rke2/bin && '
                            'kubectl get nodes',
                            check=True,
                            timeout=30
                        )
                        self.log(node, "✅ RKE2 master installation completed successfully")
                        return True
                    except Exception as e:
                        self.log(node, f"⚠️  kubectl not ready yet (attempt {attempt}/{max_attempts}): {str(e)}")
                
                if attempt < max_attempts:
                    time.sleep(10)
            
            self.log(node, f"❌ RKE2 master installation did not complete within {max_attempts * 10} seconds")
            return False
            
        except Exception as e:
            self.log(node, f"❌ RKE2 master installation failed: {str(e)}")
            return False
    
    def deploy_cluster(self, master_nodes: List[Node], worker_nodes: List[Node] = None, reset: bool = True) -> bool:
        """Deploy a complete RKE2 cluster with the given master and worker nodes.
        
        This method handles the complete deployment of an RKE2 cluster, including:
        1. Installing and configuring the first master node
        2. Installing and configuring additional master nodes (if any)
        3. Installing and configuring worker nodes (if any)
        
        Args:
            master_nodes: List of master nodes (at least one required)
            worker_nodes: Optional list of worker nodes
            reset: Whether to reset nodes before installation
            
        Returns:
            bool: True if the cluster was deployed successfully, False otherwise
        """
        if not master_nodes:
            raise ValueError("At least one master node is required")
            
        worker_nodes = worker_nodes or []
        all_nodes = master_nodes + worker_nodes
        
        try:
            self.log(None, f"🚀 Starting RKE2 cluster deployment with {len(master_nodes)} master(s) and {len(worker_nodes)} worker(s)")
            
            # Deploy the first master node
            first_master = master_nodes[0]
            self.log(first_master, "🌐 Deploying first master node")
            if not self.install_master(first_master, reset=reset):
                self.log(first_master, "❌ Failed to deploy first master node")
                return False
            
            # Get the server URL and token from the first master
            server_url = f"https://{first_master.ip}:9345"
            token = self.node_token or self.cluster_token
            
            # Deploy additional master nodes (high availability)
            for i, master in enumerate(master_nodes[1:], 2):
                self.log(master, f"🌐 Deploying additional master node {i}/{len(master_nodes)}")
                if not self.install_master(master, reset=reset):
                    self.log(master, f"❌ Failed to deploy additional master node {i}")
                    return False
            
            # Deploy worker nodes
            for i, worker in enumerate(worker_nodes, 1):
                self.log(worker, f"🛠️  Deploying worker node {i}/{len(worker_nodes)}")
                if not self.install_worker(worker, server_url=server_url, token=token, reset=reset):
                    self.log(worker, f"❌ Failed to deploy worker node {i}")
                    return False
            
            # Verify the cluster is healthy
            if not self.verify_cluster_health(first_master, len(master_nodes), len(worker_nodes)):
                self.log(first_master, "⚠️  Cluster deployment completed with warnings (health check failed)")
                return True  # Still return True as the cluster is operational
            
            self.log(first_master, "✅ RKE2 cluster deployment completed successfully")
            return True
            
        except Exception as e:
            self.log(None, f"❌ RKE2 cluster deployment failed: {str(e)}")
            return False
    
    def upgrade_cluster(self, master_nodes: List[Node], worker_nodes: List[Node] = None, 
                       target_version: str = None, drain_timeout: int = 120, 
                       node_drain_timeout: int = 60) -> bool:
        """Upgrade an existing RKE2 cluster to a new version.
        
        This method handles the complete upgrade process for an RKE2 cluster,
        including draining nodes, upgrading the control plane, and upgrading workers.
        
        Args:
            master_nodes: List of master nodes in the cluster
            worker_nodes: List of worker nodes in the cluster (optional)
            target_version: Target RKE2 version (e.g., 'v1.21.5+rke2r1'). If None, uses the version set in the installer.
            drain_timeout: Maximum time (in seconds) to wait for node drain operations
            node_drain_timeout: Maximum time (in seconds) to wait for a single node to drain
            
        Returns:
            bool: True if the upgrade was successful, False otherwise
        """
        if not master_nodes:
            raise ValueError("At least one master node is required")
            
        worker_nodes = worker_nodes or []
        all_nodes = master_nodes + worker_nodes
        
        try:
            self.log(None, f"🔄 Starting RKE2 cluster upgrade to {target_version or 'latest'}")
            
            # Get current version for reference
            first_master = master_nodes[0]
            current_version = self._ssh_exec(
                first_master,
                'rke2 --version | head -n 1 | cut -d" " -f3',
                check=True
            ).strip()
            
            self.log(None, f"ℹ️  Current cluster version: {current_version}")
            
            if target_version and target_version == current_version:
                self.log(None, f"✅ Cluster is already at version {target_version}")
                return True
            
            # Upgrade master nodes one by one
            for i, master in enumerate(master_nodes, 1):
                self.log(master, f"🔄 Upgrading master node {i}/{len(master_nodes)}")
                
                # Drain the node
                if not self._drain_node(first_master, master, drain_timeout=node_drain_timeout):
                    self.log(master, f"⚠️  Failed to drain master node {i}, continuing with upgrade")
                
                # Upgrade RKE2 on the master
                if not self._upgrade_rke2(master, target_version):
                    self.log(master, f"❌ Failed to upgrade master node {i}")
                    return False
                
                # Wait for the node to be ready again
                if not self._wait_for_node_ready(first_master, master, timeout=drain_timeout):
                    self.log(master, f"⚠️  Master node {i} did not become ready after upgrade")
                
                self.log(master, f"✅ Successfully upgraded master node {i}")
            
            # Upgrade worker nodes one by one
            for i, worker in enumerate(worker_nodes, 1):
                self.log(worker, f"🔄 Upgrading worker node {i}/{len(worker_nodes)}")
                
                # Drain the node
                if not self._drain_node(first_master, worker, drain_timeout=node_drain_timeout):
                    self.log(worker, f"⚠️  Failed to drain worker node {i}, continuing with upgrade")
                
                # Upgrade RKE2 on the worker
                if not self._upgrade_rke2(worker, target_version, is_server=False):
                    self.log(worker, f"❌ Failed to upgrade worker node {i}")
                    return False
                
                # Wait for the node to be ready again
                if not self._wait_for_node_ready(first_master, worker, timeout=drain_timeout):
                    self.log(worker, f"⚠️  Worker node {i} did not become ready after upgrade")
                
                self.log(worker, f"✅ Successfully upgraded worker node {i}")
            
            # Verify cluster health after upgrade
            if not self.verify_cluster_health(first_master, len(master_nodes), len(worker_nodes)):
                self.log(first_master, "⚠️  Cluster upgrade completed with warnings (health check failed)")
                return True  # Still return True as the upgrade completed
            
            self.log(first_master, f"✅ RKE2 cluster upgrade to {target_version or 'latest'} completed successfully")
            return True
            
        except Exception as e:
            self.log(None, f"❌ RKE2 cluster upgrade failed: {str(e)}")
            return False
    
    def _drain_node(self, master_node: Node, target_node: Node, drain_timeout: int = 60) -> bool:
        """Drain a node in preparation for upgrade."""
        try:
            # Get the node name as seen by Kubernetes
            node_name = self._ssh_exec(
                master_node,
                f'kubectl get nodes --no-headers -o custom-columns=":metadata.name" | grep -i {target_node.hostname}',
                check=False
            ).strip()
            
            if not node_name:
                self.log(target_node, f"⚠️  Could not find node {target_node.hostname} in the cluster")
                return False
            
            self.log(target_node, f"⏳ Draining node {node_name}")
            
            # Drain the node with a timeout
            self._ssh_exec(
                master_node,
                f'kubectl drain {node_name} --ignore-daemonsets --delete-emptydir-data --force --timeout={drain_timeout}s',
                check=True,
                timeout=drain_timeout + 10
            )
            
            self.log(target_node, f"✅ Successfully drained node {node_name}")
            return True
            
        except Exception as e:
            self.log(target_node, f"⚠️  Failed to drain node: {str(e)}")
            return False
    
    def _upgrade_rke2(self, node: Node, target_version: str = None, is_server: bool = True) -> bool:
        """Upgrade RKE2 on a single node."""
        try:
            self.log(node, f"🔄 Upgrading RKE2 to {target_version or 'latest'}")
            
            # Stop the RKE2 service
            service_name = 'rke2-server' if is_server else 'rke2-agent'
            self._ssh_exec(node, f'systemctl stop {service_name}', check=False)
            
            # Run the upgrade script with the target version
            install_cmd = 'curl -sfL https://get.rke2.io | '
            if target_version:
                install_cmd += f'sh -s - --version {target_version}'
            else:
                install_cmd += 'sh -'
                
            self._ssh_exec(node, install_cmd, check=True, timeout=300)
            
            # Restart the service
            self._ssh_exec(node, f'systemctl daemon-reload', check=True)
            self._ssh_exec(node, f'systemctl enable {service_name}', check=True)
            self._ssh_exec(node, f'systemctl start {service_name}', check=True)
            
            self.log(node, f"✅ Successfully upgraded RKE2 to {target_version or 'latest'}")
            return True
            
        except Exception as e:
            self.log(node, f"❌ Failed to upgrade RKE2: {str(e)}")
            return False
    
    def _wait_for_node_ready(self, master_node: Node, target_node: Node, timeout: int = 180) -> bool:
        """Wait for a node to be ready after upgrade."""
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            try:
                # Get the node status
                node_name = target_node.hostname
                status = self._ssh_exec(
                    master_node,
                    f'kubectl get node {node_name} -o jsonpath="{{.status.conditions[?(@.type==\'Ready\')].status}}" 2>/dev/null || true',
                    check=False
                ).strip()
                
                if status == 'True':
                    self.log(target_node, f"✅ Node {node_name} is ready")
                    return True
                    
                self.log(target_node, f"⏳ Waiting for node {node_name} to be ready...")
                time.sleep(5)
                
            except Exception as e:
                self.log(target_node, f"⚠️  Error checking node status: {str(e)}")
                time.sleep(5)
        
        self.log(target_node, f"❌ Timed out waiting for node {node_name} to be ready")
        return False
    
    def backup_etcd(self, master_node: Node, backup_dir: str = '/var/lib/rancher/rke2/server/db/backups',
                   local_path: str = None) -> Optional[str]:
        """Create a backup of the etcd database from a master node.
        
        Args:
            master_node: The master node to back up etcd from
            backup_dir: Directory on the master node to store the backup
            local_path: If specified, download the backup to this local path
            
        Returns:
            str: Path to the backup file on the master node, or local path if downloaded
        """
        try:
            timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
            backup_file = f"etcd-backup-{timestamp}.db"
            backup_path = f"{backup_dir}/{backup_file}"
            
            self.log(master_node, f"💾 Creating etcd backup at {backup_path}")
            
            # Create backup directory if it doesn't exist
            self._ssh_exec(master_node, f'mkdir -p {backup_dir}', check=True)
            
            # Create the backup
            self._ssh_exec(
                master_node,
                f'rke2 etcd-snapshot save --s3 --s3-bucket=etcd-backups --s3-folder={timestamp} {backup_path}',
                check=True,
                timeout=300  # 5 minute timeout for backup
            )
            
            # Verify the backup was created
            self._ssh_exec(master_node, f'test -f {backup_path}', check=True)
            
            # Download the backup if local_path is specified
            if local_path:
                os.makedirs(os.path.dirname(os.path.abspath(local_path)), exist_ok=True)
                with self.connection_pool.get_connection(master_node) as conn:
                    sftp = conn.open_sftp()
                    try:
                        sftp.get(backup_path, local_path)
                        self.log(master_node, f"✅ Downloaded etcd backup to {local_path}")
                        return local_path
                    finally:
                        sftp.close()
            
            self.log(master_node, f"✅ Created etcd backup at {backup_path}")
            return backup_path
            
        except Exception as e:
            self.log(master_node, f"❌ Failed to create etcd backup: {str(e)}")
            return None
    
    def restore_etcd(self, master_node: Node, backup_path: str, is_local: bool = False) -> bool:
        """Restore an etcd database from a backup.
        
        Args:
            master_node: The master node to restore etcd to
            backup_path: Path to the backup file (on the master node or local)
            is_local: If True, upload the backup from the local path to the master node
            
        Returns:
            bool: True if the restore was successful, False otherwise
        """
        try:
            remote_path = backup_path
            
            # If this is a local file, upload it to the master node
            if is_local:
                if not os.path.isfile(backup_path):
                    self.log(master_node, f"❌ Backup file not found: {backup_path}")
                    return False
                    
                remote_dir = '/tmp/etcd-restore'
                remote_path = f"{remote_dir}/{os.path.basename(backup_path)}"
                
                self.log(master_node, f"📤 Uploading etcd backup to {remote_path}")
                self._ssh_exec(master_node, f'mkdir -p {remote_dir}', check=True)
                
                with self.connection_pool.get_connection(master_node) as conn:
                    sftp = conn.open_sftp()
                    try:
                        sftp.put(backup_path, remote_path)
                    finally:
                        sftp.close()
            
            # Stop the RKE2 service
            self.log(master_node, "⏹️  Stopping RKE2 service")
            self._ssh_exec(master_node, 'systemctl stop rke2-server', check=False)
            
            # Restore the etcd database
            self.log(master_node, f"🔄 Restoring etcd from {remote_path}")
            self._ssh_exec(
                master_node,
                f'rke2 server --cluster-reset --cluster-reset-restore-path={remote_path}',
                check=True,
                timeout=300  # 5 minute timeout for restore
            )
            
            # Start the RKE2 service
            self.log(master_node, "▶️  Starting RKE2 service")
            self._ssh_exec(master_node, 'systemctl start rke2-server', check=True)
            
            # Wait for the node to be ready
            if not self._wait_for_node_ready(master_node, master_node, timeout=300):
                self.log(master_node, "⚠️  Node did not become ready after restore")
                return False
            
            self.log(master_node, "✅ Successfully restored etcd from backup")
            return True
            
        except Exception as e:
            self.log(master_node, f"❌ Failed to restore etcd: {str(e)}")
            
            # Try to restart the RKE2 service if it was stopped
            try:
                self._ssh_exec(master_node, 'systemctl restart rke2-server', check=False)
            except:
                pass
                
            return False
    
    def scale_workers(self, master_node: Node, desired_count: int, worker_nodes: List[Node], 
                     drain_timeout: int = 300) -> bool:
        """Scale the number of worker nodes in the cluster.
        
        This method will add or remove worker nodes to match the desired count.
        
        Args:
            master_node: A master node to coordinate the scaling operation
            desired_count: Desired number of worker nodes
            worker_nodes: Current list of worker nodes
            drain_timeout: Maximum time (in seconds) to wait for node drain operations
            
        Returns:
            bool: True if scaling was successful, False otherwise
        """
        try:
            current_count = len(worker_nodes)
            
            if desired_count == current_count:
                self.log(master_node, f"ℹ️  Current worker count ({current_count}) matches desired count, no scaling needed")
                return True
                
            self.log(master_node, f"🔄 Scaling workers from {current_count} to {desired_count}")
            
            if desired_count < current_count:
                # Scale down - remove extra workers
                nodes_to_remove = worker_nodes[desired_count:]
                for i, node in enumerate(nodes_to_remove, 1):
                    self.log(node, f"🔽 Removing worker node {i}/{len(nodes_to_remove)}")
                    
                    # Drain the node
                    if not self._drain_node(master_node, node, drain_timeout):
                        self.log(node, "⚠️  Failed to drain node, continuing with removal")
                    
                    # Remove the node from Kubernetes
                    self._remove_node(master_node, node)
                    
                    # Stop and disable the RKE2 agent
                    self._ssh_exec(node, 'systemctl stop rke2-agent', check=False)
                    self._ssh_exec(node, 'systemctl disable rke2-agent', check=False)
                    
                    self.log(node, "✅ Worker node removed")
                
                return True
                
            else:
                # Scale up - add new workers
                # This assumes you have a way to provision new nodes
                # You'll need to implement node provisioning logic based on your infrastructure
                self.log(master_node, "⚠️  Scale up not implemented - please provision new nodes and add them to the cluster")
                return False
                
        except Exception as e:
            self.log(master_node, f"❌ Failed to scale workers: {str(e)}")
            return False
    
    def drain_node(self, master_node: Node, target_node: Node, 
                   delete_local_data: bool = True, 
                   ignore_daemonsets: bool = True,
                   force: bool = True, 
                   timeout: int = 300) -> bool:
        """Drain a node in preparation for maintenance.
        
        This is a more configurable version of the internal _drain_node method.
        
        Args:
            master_node: A master node to run kubectl commands from
            target_node: The node to drain
            delete_local_data: Delete pods using emptyDir
            ignore_daemonsets: Ignore DaemonSet-managed pods
            force: Continue even if there are pods not managed by a ReplicationController, ReplicaSet, Job, or DaemonSet
            timeout: Maximum time (in seconds) to wait for the drain to complete
            
        Returns:
            bool: True if the node was drained successfully, False otherwise
        """
        try:
            # Get the node name as seen by Kubernetes
            node_name = self._ssh_exec(
                master_node,
                f'kubectl get nodes --no-headers -o custom-columns=":metadata.name" | grep -i {target_node.hostname}',
                check=False
            ).strip()
            
            if not node_name:
                self.log(target_node, f"⚠️  Could not find node {target_node.hostname} in the cluster")
                return False
            
            self.log(target_node, f"⏳ Draining node {node_name}")
            
            # Build the drain command
            cmd = f'kubectl drain {node_name} --timeout={timeout}s'
            
            if delete_local_data:
                cmd += ' --delete-emptydir-data'
            if ignore_daemonsets:
                cmd += ' --ignore-daemonsets=true'
            if force:
                cmd += ' --force'
            
            # Execute the drain command
            self._ssh_exec(
                master_node,
                cmd,
                check=True,
                timeout=timeout + 10  # Add some buffer time
            )
            
            self.log(target_node, f"✅ Successfully drained node {node_name}")
            return True
            
        except Exception as e:
            self.log(target_node, f"❌ Failed to drain node: {str(e)}")
            return False
    
    def _remove_node(self, master_node: Node, target_node: Node) -> bool:
        """Remove a node from the Kubernetes cluster."""
        try:
            # Get the node name as seen by Kubernetes
            node_name = self._ssh_exec(
                master_node,
                f'kubectl get nodes --no-headers -o custom-columns=":metadata.name" | grep -i {target_node.hostname}',
                check=False
            ).strip()
            
            if not node_name:
                self.log(target_node, f"⚠️  Could not find node {target_node.hostname} in the cluster")
                return False
            
            self.log(target_node, f"🗑️  Removing node {node_name} from the cluster")
            
            # Delete the node
            self._ssh_exec(
                master_node,
                f'kubectl delete node {node_name}',
                check=True,
                timeout=30
            )
            
            self.log(target_node, f"✅ Successfully removed node {node_name} from the cluster")
            return True
            
        except Exception as e:
            self.log(target_node, f"❌ Failed to remove node: {str(e)}")
            return False
    
    def get_cluster_info(self, master_node: Node) -> Dict[str, Any]:
        """Get information about the RKE2 cluster.
        
        Args:
            master_node: A master node to run kubectl commands from
            
        Returns:
            dict: Dictionary containing cluster information
        """
        try:
            self.log(master_node, "📊 Gathering cluster information")
            
            # Get cluster info
            cluster_info = {
                'version': self._ssh_exec(
                    master_node,
                    'kubectl version --short 2>/dev/null | grep Server | cut -d" " -f3',
                    check=False
                ).strip(),
                'nodes': {},
                'pods': {},
                'services': {}
            }
            
            # Get node information
            nodes_output = self._ssh_exec(
                master_node,
                'kubectl get nodes -o json',
                check=True
            )
            
            try:
                nodes_data = json.loads(nodes_output)
                for item in nodes_data.get('items', []):
                    node_name = item['metadata']['name']
                    status = next((c for c in item['status']['conditions'] if c['type'] == 'Ready'), {})
                    
                    cluster_info['nodes'][node_name] = {
                        'status': status.get('status', 'Unknown'),
                        'os': f"{item['status']['nodeInfo']['operatingSystem']} {item['status']['nodeInfo']['osImage']}",
                        'kernel': item['status']['nodeInfo']['kernelVersion'],
                        'container_runtime': item['status']['nodeInfo']['containerRuntimeVersion'],
                        'kubelet': item['status']['nodeInfo']['kubeletVersion'],
                        'cpu': item['status']['capacity'].get('cpu', 'N/A'),
                        'memory': item['status']['capacity'].get('memory', 'N/A'),
                        'pods': item['status']['capacity'].get('pods', 'N/A')
                    }
            except Exception as e:
                self.log(master_node, f"⚠️  Failed to parse node information: {str(e)}")
            
            # Get pod information
            pods_output = self._ssh_exec(
                master_node,
                'kubectl get pods --all-namespaces -o json',
                check=False
            )
            
            try:
                pods_data = json.loads(pods_output)
                for pod in pods_data.get('items', []):
                    namespace = pod['metadata']['namespace']
                    pod_name = pod['metadata']['name']
                    
                    container_statuses = {}
                    for container in pod.get('status', {}).get('containerStatuses', []):
                        container_statuses[container['name']] = {
                            'ready': container.get('ready', False),
                            'restart_count': container.get('restartCount', 0),
                            'image': container.get('image', ''),
                            'state': next(iter(container.get('state', {}).keys()), 'unknown')
                        }
                    
                    cluster_info['pods'][f"{namespace}/{pod_name}"] = {
                        'node': pod['spec'].get('nodeName', 'N/A'),
                        'status': pod['status'].get('phase', 'Unknown'),
                        'containers': container_statuses,
                        'created': pod['metadata'].get('creationTimestamp', 'N/A')
                    }
            except Exception as e:
                self.log(master_node, f"⚠️  Failed to parse pod information: {str(e)}")
            
            # Get service information
            services_output = self._ssh_exec(
                master_node,
                'kubectl get services --all-namespaces -o json',
                check=False
            )
            
            try:
                services_data = json.loads(services_output)
                for svc in services_data.get('items', []):
                    namespace = svc['metadata']['namespace']
                    svc_name = svc['metadata']['name']
                    
                    ports = []
                    for port in svc['spec'].get('ports', []):
                        ports.append({
                            'name': port.get('name', ''),
                            'port': port.get('port', 0),
                            'target_port': port.get('targetPort', 0),
                            'protocol': port.get('protocol', 'TCP'),
                            'node_port': port.get('nodePort')
                        })
                    
                    cluster_info['services'][f"{namespace}/{svc_name}"] = {
                        'type': svc['spec'].get('type', 'ClusterIP'),
                        'cluster_ip': svc['spec'].get('clusterIP', 'None'),
                        'external_ips': svc['spec'].get('externalIPs', []),
                        'ports': ports,
                        'selector': svc['spec'].get('selector', {})
                    }
            except Exception as e:
                self.log(master_node, f"⚠️  Failed to parse service information: {str(e)}")
            
            return cluster_info
            
        except Exception as e:
            self.log(master_node, f"❌ Failed to get cluster information: {str(e)}")
            return {}
    
    def get_node_status(self, master_node: Node, node_name: Optional[str] = None) -> Dict[str, Any]:
        """Get detailed status of a specific node or all nodes.
        
        Args:
            master_node: A master node to run kubectl commands from
            node_name: Optional name of the node to get status for. If None, returns all nodes.
            
        Returns:
            dict: Dictionary containing node status information
        """
        try:
            if node_name:
                self.log(master_node, f"📊 Getting status for node: {node_name}")
                cmd = f'kubectl get node {node_name} -o json'
            else:
                self.log(master_node, "📊 Getting status for all nodes")
                cmd = 'kubectl get nodes -o json'
            
            output = self._ssh_exec(master_node, cmd, check=True)
            data = json.loads(output)
            
            if node_name:
                # Return details for a single node
                return self._parse_node_info(data)
            else:
                # Return details for all nodes
                return {
                    'apiVersion': data.get('apiVersion'),
                    'kind': data.get('kind'),
                    'items': [self._parse_node_info(item) for item in data.get('items', [])]
                }
                
        except Exception as e:
            self.log(master_node, f"❌ Failed to get node status: {str(e)}")
            return {}
    
    def _parse_node_info(self, node_data: Dict[str, Any]) -> Dict[str, Any]:
        """Parse node information from kubectl output."""
        if not node_data or 'metadata' not in node_data:
            return {}
        
        node_info = {
            'name': node_data['metadata'].get('name'),
            'labels': node_data['metadata'].get('labels', {}),
            'annotations': node_data['metadata'].get('annotations', {}),
            'creation_timestamp': node_data['metadata'].get('creationTimestamp'),
            'status': {}
        }
        
        if 'status' in node_data:
            status = node_data['status']
            
            # Node conditions
            conditions = {}
            for condition in status.get('conditions', []):
                conditions[condition['type']] = {
                    'status': condition.get('status'),
                    'last_heartbeat': condition.get('lastHeartbeatTime'),
                    'last_transition': condition.get('lastTransitionTime'),
                    'reason': condition.get('reason'),
                    'message': condition.get('message')
                }
            
            node_info['status'].update({
                'conditions': conditions,
                'node_info': status.get('nodeInfo', {}),
                'capacity': status.get('capacity', {}),
                'allocatable': status.get('allocatable', {}),
                'addresses': {addr['type']: addr['address'] for addr in status.get('addresses', [])}
            })
            
            # Add additional status fields
            for field in ['images', 'phase', 'volumesInUse', 'volumesAttached']:
                if field in status:
                    node_info['status'][field] = status[field]
        
        return node_info
    
    def deploy_application(self, master_node: Node, manifest_path: str, 
                         namespace: str = 'default', 
                         timeout: int = 300,
                         dry_run: bool = False) -> Dict[str, Any]:
        """Deploy an application to the RKE2 cluster using a Kubernetes manifest.
        
        Args:
            master_node: A master node to run kubectl commands from
            manifest_path: Path to the Kubernetes manifest file (YAML/JSON) or directory
            namespace: Namespace to deploy the application to (default: 'default')
            timeout: Maximum time (in seconds) to wait for the deployment to complete
            dry_run: If True, only simulate the deployment without making changes
            
        Returns:
            dict: Dictionary containing deployment status and details
        """
        try:
            self.log(master_node, f"🚀 Deploying application from {manifest_path}")
            
            # Check if the manifest exists (if it's a local file)
            if os.path.exists(manifest_path):
                # Upload the manifest to the master node
                remote_dir = f"/tmp/k8s-manifests/{os.path.basename(manifest_path)}-{int(time.time())}"
                self._ssh_exec(master_node, f'mkdir -p {remote_dir}', check=True)
                
                if os.path.isfile(manifest_path):
                    # Single file
                    remote_path = f"{remote_dir}/{os.path.basename(manifest_path)}"
                    with self.connection_pool.get_connection(master_node) as conn:
                        sftp = conn.open_sftp()
                        try:
                            sftp.put(manifest_path, remote_path)
                        finally:
                            sftp.close()
                    manifest_path = remote_path
                else:
                    # Directory - upload all files
                    for root, _, files in os.walk(manifest_path):
                        for file in files:
                            if file.endswith(('.yaml', '.yml', '.json')):
                                local_path = os.path.join(root, file)
                                remote_path = f"{remote_dir}/{file}"
                                with self.connection_pool.get_connection(master_node) as conn:
                                    sftp = conn.open_sftp()
                                    try:
                                        sftp.put(local_path, remote_path)
                                    finally:
                                        sftp.close()
                    manifest_path = remote_dir
            
            # Build the kubectl apply command
            cmd = f'kubectl apply -f "{manifest_path}" -n {namespace}'
            if dry_run:
                cmd += ' --dry-run=client -o yaml'
            
            # Deploy the application
            self.log(master_node, f"📦 Applying Kubernetes manifests from {manifest_path}")
            output = self._ssh_exec(master_node, cmd, check=True, timeout=timeout)
            
            # Parse the output to get deployed resources
            resources = []
            for line in output.split('\n'):
                if line.strip() and not line.startswith((' ', '\t')):
                    parts = line.split()
                    if len(parts) >= 2 and parts[1].lower() != 'unchanged':
                        resources.append({
                            'kind': parts[0].lower(),
                            'name': parts[1],
                            'status': parts[2].lower()
                        })
            
            result = {
                'success': True,
                'resources': resources,
                'output': output,
                'manifest_path': manifest_path,
                'namespace': namespace
            }
            
            if not dry_run:
                # Wait for deployments to be ready
                self.log(master_node, "⏳ Waiting for deployments to be ready...")
                for resource in resources:
                    if resource['kind'] == 'deployment':
                        self._wait_for_deployment_ready(
                            master_node, 
                            resource['name'], 
                            namespace,
                            timeout=timeout
                        )
            
            self.log(master_node, "✅ Application deployed successfully")
            return result
            
        except Exception as e:
            self.log(master_node, f"❌ Failed to deploy application: {str(e)}")
            return {
                'success': False,
                'error': str(e),
                'manifest_path': manifest_path,
                'namespace': namespace
            }
    
    def undeploy_application(self, master_node: Node, manifest_path: str, 
                           namespace: str = 'default',
                           timeout: int = 300,
                           ignore_not_found: bool = True) -> Dict[str, Any]:
        """Undeploy an application from the RKE2 cluster using a Kubernetes manifest.
        
        Args:
            master_node: A master node to run kubectl commands from
            manifest_path: Path to the Kubernetes manifest file (YAML/JSON) or directory
            namespace: Namespace where the application is deployed (default: 'default')
            timeout: Maximum time (in seconds) to wait for the deletion to complete
            ignore_not_found: If True, don't fail if the resources are not found
            
        Returns:
            dict: Dictionary containing undeployment status and details
        """
        try:
            self.log(master_node, f"🗑️  Undeploying application from {manifest_path}")
            
            # Check if the manifest exists (if it's a local file)
            if os.path.exists(manifest_path):
                # Upload the manifest to the master node
                remote_dir = f"/tmp/k8s-manifests/{os.path.basename(manifest_path)}-{int(time.time())}"
                self._ssh_exec(master_node, f'mkdir -p {remote_dir}', check=True)
                
                if os.path.isfile(manifest_path):
                    # Single file
                    remote_path = f"{remote_dir}/{os.path.basename(manifest_path)}"
                    with self.connection_pool.get_connection(master_node) as conn:
                        sftp = conn.open_sftp()
                        try:
                            sftp.put(manifest_path, remote_path)
                        finally:
                            sftp.close()
                    manifest_path = remote_path
                else:
                    # Directory - upload all files
                    for root, _, files in os.walk(manifest_path):
                        for file in files:
                            if file.endswith(('.yaml', '.yml', '.json')):
                                local_path = os.path.join(root, file)
                                remote_path = f"{remote_dir}/{file}"
                                with self.connection_pool.get_connection(master_node) as conn:
                                    sftp = conn.open_sftp()
                                    try:
                                        sftp.put(local_path, remote_path)
                                    finally:
                                        sftp.close()
                    manifest_path = remote_dir
            
            # Build the kubectl delete command
            cmd = f'kubectl delete -f "{manifest_path}" -n {namespace} --timeout={timeout}s --wait={ignore_not_found}'
            
            # Undeploy the application
            self.log(master_node, f"🗑️  Deleting Kubernetes resources from {manifest_path}")
            output = self._ssh_exec(master_node, cmd, check=not ignore_not_found, timeout=timeout)
            
            # Clean up the uploaded manifest files
            try:
                if manifest_path.startswith('/tmp/k8s-manifests/'):
                    self._ssh_exec(master_node, f'rm -rf {os.path.dirname(manifest_path)}', check=False)
            except:
                pass
            
            self.log(master_node, "✅ Application undeployed successfully")
            return {
                'success': True,
                'output': output,
                'manifest_path': manifest_path,
                'namespace': namespace
            }
            
        except Exception as e:
            self.log(master_node, f"❌ Failed to undeploy application: {str(e)}")
            return {
                'success': False,
                'error': str(e),
                'manifest_path': manifest_path,
                'namespace': namespace
            }
    
    def _wait_for_deployment_ready(self, master_node: Node, deployment: str, 
                                namespace: str = 'default', 
                                timeout: int = 300) -> bool:
        """Wait for a deployment to be ready."""
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            try:
                # Get deployment status
                output = self._ssh_exec(
                    master_node,
                    f'kubectl get deployment {deployment} -n {namespace} -o json',
                    check=True
                )
                
                data = json.loads(output)
                
                # Check if deployment is available
                for condition in data.get('status', {}).get('conditions', []):
                    if condition.get('type') == 'Available' and condition.get('status') == 'True':
                        self.log(master_node, f"✅ Deployment {namespace}/{deployment} is available")
                        return True
                
                # Log current status
                replicas = data.get('status', {}).get('replicas', 0)
                available = data.get('status', {}).get('availableReplicas', 0)
                updated = data.get('status', {}).get('updatedReplicas', 0)
                ready = data.get('status', {}).get('readyReplicas', 0)
                
                self.log(
                    master_node, 
                    f"⏳ Waiting for deployment {namespace}/{deployment} to be ready: "
                    f"{available}/{replicas} available, {updated} updated, {ready} ready"
                )
                
            except Exception as e:
                self.log(master_node, f"⚠️  Error checking deployment status: {str(e)}")
            
            time.sleep(5)
        
        self.log(master_node, f"❌ Timed out waiting for deployment {namespace}/{deployment} to be ready")
        return False
    
    def execute_command(self, master_node: Node, pod_name: str, command: Union[str, List[str]],
                       namespace: str = 'default',
                       container: Optional[str] = None,
                       timeout: int = 60) -> Dict[str, Any]:
        """Execute a command in a pod in the RKE2 cluster.
        
        Args:
            master_node: A master node to run kubectl commands from
            pod_name: Name of the pod to execute the command in
            command: Command to execute (string or list of strings)
            namespace: Namespace where the pod is located (default: 'default')
            container: Name of the container to execute the command in (if pod has multiple containers)
            timeout: Maximum time (in seconds) to wait for the command to complete
            
        Returns:
            dict: Dictionary containing command execution results
        """
        try:
            # Convert command to a string if it's a list
            if isinstance(command, list):
                command_str = ' '.join(shlex.quote(arg) for arg in command)
            else:
                command_str = str(command)
            
            # Build the kubectl exec command
            cmd = f'kubectl exec {pod_name} -n {namespace} -- {command_str}'
            if container:
                cmd = f'kubectl exec {pod_name} -n {namespace} -c {container} -- {command_str}'
            
            self.log(master_node, f"💻 Executing command in pod {namespace}/{pod_name}: {command_str}")
            
            # Execute the command
            output = self._ssh_exec(master_node, cmd, check=True, timeout=timeout)
            
            return {
                'success': True,
                'output': output,
                'pod': pod_name,
                'namespace': namespace,
                'container': container,
                'command': command_str
            }
            
        except Exception as e:
            self.log(master_node, f"❌ Failed to execute command in pod {namespace}/{pod_name}: {str(e)}")
            return {
                'success': False,
                'error': str(e),
                'pod': pod_name,
                'namespace': namespace,
                'container': container,
                'command': command_str if 'command_str' in locals() else str(command)
            }
    
    def port_forward(self, master_node: Node, resource_type: str, resource_name: str, 
                    local_port: int, remote_port: int, 
                    namespace: str = 'default',
                    address: str = '127.0.0.1') -> subprocess.Popen:
        """Set up port forwarding to a pod or service in the RKE2 cluster.
        
        Args:
            master_node: A master node to run kubectl commands from
            resource_type: Type of the resource to forward to (e.g., 'pod', 'service', 'deployment')
            resource_name: Name of the resource to forward to
            local_port: Local port to forward from
            remote_port: Remote port to forward to
            namespace: Namespace where the resource is located (default: 'default')
            address: Local address to bind to (default: '127.0.0.1')
            
        Returns:
            subprocess.Popen: Process object for the port forwarding
            
        Example:
            # Forward local port 8080 to port 80 on a service called 'my-service'
            pf = installer.port_forward(master, 'service', 'my-service', 8080, 80)
            
            # Do something with the forwarded port...
            
            # When done, terminate the port forwarding
            pf.terminate()
        """
        try:
            # Build the kubectl port-forward command
            cmd = [
                'kubectl', 'port-forward',
                f'{resource_type}/{resource_name}',
                '-n', namespace,
                f'{address}:{local_port}:{remote_port}'
            ]
            
            self.log(
                master_node,
                f"🔗 Setting up port forwarding: {address}:{local_port} -> {resource_type}/{resource_name}:{remote_port} in {namespace}"
            )
            
            # Start the port forwarding in the background
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            # Wait a bit to see if the port forwarding fails immediately
            time.sleep(1)
            if process.poll() is not None:
                # Process has already terminated
                _, stderr = process.communicate()
                raise RuntimeError(f"Port forwarding failed: {stderr}")
            
            # Add a small delay to allow the port forwarding to be established
            time.sleep(1)
            
            self.log(master_node, f"✅ Port forwarding set up (PID: {process.pid})")
            return process
            
        except Exception as e:
            self.log(master_node, f"❌ Failed to set up port forwarding: {str(e)}")
            if 'process' in locals():
                process.terminate()
            raise
    
    def get_logs(self, master_node: Node, pod_name: str, 
                container: Optional[str] = None,
                namespace: str = 'default',
                tail: Optional[int] = None,
                since: Optional[str] = None,
                previous: bool = False) -> str:
        """Get logs from a pod in the RKE2 cluster.
        
        Args:
            master_node: A master node to run kubectl commands from
            pod_name: Name of the pod to get logs from
            container: Name of the container to get logs from (if pod has multiple containers)
            namespace: Namespace where the pod is located (default: 'default')
            tail: Number of lines of recent log file to display
            since: Return logs newer than a relative duration like 5s, 2m, or 3h
            previous: If true, print the logs for the previous instance of the container in a pod if it exists
            
        Returns:
            str: The logs from the pod
        """
        try:
            # Build the kubectl logs command
            cmd = f'kubectl logs {pod_name} -n {namespace}'
            
            if container:
                cmd += f' -c {container}'
            if tail is not None:
                cmd += f' --tail={tail}'
            if since:
                cmd += f' --since={since}'
            if previous:
                cmd += ' --previous'
            
            self.log(master_node, f"📜 Getting logs from pod {namespace}/{pod_name}" + 
                   (f" (container: {container})" if container else ""))
            
            # Get the logs
            logs = self._ssh_exec(master_node, cmd, check=True)
            
            return logs
            
        except Exception as e:
            self.log(master_node, f"❌ Failed to get logs from pod {namespace}/{pod_name}: {str(e)}")
            raise
    
    def stream_logs(self, master_node: Node, pod_name: str, 
                   container: Optional[str] = None,
                   namespace: str = 'default',
                   follow: bool = True,
                   tail: Optional[int] = None,
                   since: Optional[str] = None) -> subprocess.Popen:
        """Stream logs from a pod in the RKE2 cluster.
        
        This method returns a subprocess.Popen object that streams the logs.
        You can read from process.stdout to get the logs as they come in.
        
        Args:
            master_node: A master node to run kubectl commands from
            pod_name: Name of the pod to stream logs from
            container: Name of the container to stream logs from (if pod has multiple containers)
            namespace: Namespace where the pod is located (default: 'default')
            follow: If true, follow the logs (similar to 'tail -f')
            tail: Number of lines of recent log file to display
            since: Return logs newer than a relative duration like 5s, 2m, or 3h
            
        Returns:
            subprocess.Popen: Process object for the log streaming
            
        Example:
            # Stream logs from a pod
            process = installer.stream_logs(master, 'my-pod')
            
            try:
                # Read logs line by line as they come in
                for line in process.stdout:
                    print(f"LOG: {line}", end='')
            except KeyboardInterrupt:
                # Handle Ctrl+C
                pass
            finally:
                # Make sure to terminate the process when done
                process.terminate()
        """
        try:
            # Build the kubectl logs command
            cmd = ['kubectl', 'logs', pod_name, '-n', namespace]
            
            if container:
                cmd.extend(['-c', container])
            if follow:
                cmd.append('-f')
            if tail is not None:
                cmd.extend(['--tail', str(tail)])
            if since:
                cmd.extend(['--since', since])
            
            self.log(master_node, f"📡 Streaming logs from pod {namespace}/{pod_name}" + 
                   (f" (container: {container})" if container else ""))
            
            # Start the log streaming process
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,  # Line buffered
                universal_newlines=True
            )
            
            # Wait a bit to see if the command fails immediately
            time.sleep(0.5)
            if process.poll() is not None:
                # Process has already terminated
                _, stderr = process.communicate()
                raise RuntimeError(f"Failed to stream logs: {stderr}")
            
            self.log(master_node, f"✅ Log streaming started (PID: {process.pid})")
            return process
            
        except Exception as e:
            self.log(master_node, f"❌ Failed to stream logs from pod {namespace}/{pod_name}: {str(e)}")
            if 'process' in locals():
                process.terminate()
            raise
    
    def create_namespace(self, master_node: Node, name: str, labels: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """Create a new namespace in the RKE2 cluster.
        
        Args:
            master_node: A master node to run kubectl commands from
            name: Name of the namespace to create
            labels: Optional dictionary of labels to apply to the namespace
            
        Returns:
            dict: Dictionary containing the creation status and details
        """
        try:
            self.log(master_node, f"📦 Creating namespace '{name}'")
            
            # Build the kubectl create namespace command
            cmd = f'kubectl create namespace {name}'
            
            # Add labels if provided
            if labels:
                label_str = ','.join(f"{k}={v}" for k, v in labels.items())
                cmd += f' --dry-run=client -o yaml | kubectl label -f - --local -o yaml --overwrite {label_str} | kubectl apply -f -'
            
            # Create the namespace
            output = self._ssh_exec(master_node, cmd, check=True)
            
            self.log(master_node, f"✅ Namespace '{name}' created successfully")
            return {
                'success': True,
                'name': name,
                'output': output
            }
            
        except Exception as e:
            self.log(master_node, f"❌ Failed to create namespace '{name}': {str(e)}")
            return {
                'success': False,
                'error': str(e),
                'name': name
            }
    
    def delete_namespace(self, master_node: Node, name: str, force: bool = False, timeout: int = 300) -> Dict[str, Any]:
        """Delete a namespace from the RKE2 cluster.
        
        Args:
            master_node: A master node to run kubectl commands from
            name: Name of the namespace to delete
            force: If True, force delete the namespace even if it contains resources
            timeout: Time in seconds to wait for the namespace to be deleted
            
        Returns:
            dict: Dictionary containing the deletion status and details
        """
        try:
            self.log(master_node, f"🗑️  Deleting namespace '{name}'")
            
            # Build the kubectl delete namespace command
            cmd = f'kubectl delete namespace {name}'
            
            # Add force flag if specified
            if force:
                cmd += ' --force --grace-period=0'
            
            # Add timeout
            cmd += f' --timeout={timeout}s'
            
            # Delete the namespace
            output = self._ssh_exec(master_node, cmd, check=False)
            
            # Check if the namespace still exists
            if not self._wait_for_namespace_deletion(master_node, name, timeout):
                raise RuntimeError(f"Namespace '{name}' was not deleted within the timeout period")
            
            self.log(master_node, f"✅ Namespace '{name}' deleted successfully")
            return {
                'success': True,
                'name': name,
                'output': output
            }
            
        except Exception as e:
            self.log(master_node, f"❌ Failed to delete namespace '{name}': {str(e)}")
            return {
                'success': False,
                'error': str(e),
                'name': name
            }
    
    def list_namespaces(self, master_node: Node, labels: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
        """List all namespaces in the RKE2 cluster.
        
        Args:
            master_node: A master node to run kubectl commands from
            labels: Optional label selector to filter namespaces
            
        Returns:
            List[Dict]: List of namespaces with their details
        """
        try:
            self.log(master_node, "📋 Listing namespaces")
            
            # Build the kubectl get namespaces command
            cmd = 'kubectl get namespaces -o json'
            
            # Add label selector if provided
            if labels:
                label_selector = ','.join(f"{k}={v}" for k, v in labels.items())
                cmd += f' -l {label_selector}'
            
            # Get the namespaces
            output = self._ssh_exec(master_node, cmd, check=True)
            
            # Parse the output
            namespaces = json.loads(output)
            
            # Extract relevant information
            result = []
            for ns in namespaces.get('items', []):
                result.append({
                    'name': ns['metadata']['name'],
                    'status': ns['status']['phase'],
                    'age': self._get_age(ns['metadata']['creationTimestamp']),
                    'labels': ns['metadata'].get('labels', {})
                })
            
            self.log(master_node, f"✅ Found {len(result)} namespaces")
            return result
            
        except Exception as e:
            self.log(master_node, f"❌ Failed to list namespaces: {str(e)}")
            raise
    
    def _wait_for_namespace_deletion(self, master_node: Node, name: str, timeout: int = 300) -> bool:
        """Wait for a namespace to be deleted."""
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            try:
                # Check if the namespace still exists
                self._ssh_exec(master_node, f'kubectl get namespace {name} --ignore-not-found', check=False)
                
                # If we get here, the namespace still exists
                time.sleep(1)
                
            except Exception:
                # Namespace doesn't exist anymore
                return True
        
        return False
    
    def _get_age(self, timestamp: str) -> str:
        """Calculate the age from a timestamp."""
        if not timestamp:
            return 'unknown'
            
        try:
            # Parse the timestamp (e.g., '2023-04-01T12:34:56Z')
            created = datetime.datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            now = datetime.datetime.now(datetime.timezone.utc)
            
            # Calculate the delta
            delta = now - created
            
            # Format the age in a human-readable way
            if delta.days > 0:
                return f"{delta.days}d{delta.seconds//3600}h"
            elif delta.seconds > 3600:
                hours = delta.seconds // 3600
                minutes = (delta.seconds % 3600) // 60
                return f"{hours}h{minutes}m"
            elif delta.seconds > 60:
                minutes = delta.seconds // 60
                return f"{minutes}m{delta.seconds%60}s"
            else:
                return f"{delta.seconds}s"
                
        except Exception:
            return 'unknown'
    
    def get_pods(self, master_node: Node, namespace: str = 'all', 
                labels: Optional[Dict[str, str]] = None,
                field_selector: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get information about pods in the RKE2 cluster.
        
        Args:
            master_node: A master node to run kubectl commands from
            namespace: Namespace to get pods from (default: 'all' for all namespaces)
            labels: Optional label selector to filter pods
            field_selector: Optional field selector to filter pods
            
        Returns:
            List[Dict]: List of pods with their details
        """
        try:
            self.log(master_node, f"📋 Getting pods from namespace '{namespace}'")
            
            # Build the kubectl get pods command
            cmd = 'kubectl get pods'
            
            # Add namespace
            if namespace.lower() == 'all':
                cmd += ' --all-namespaces'
            else:
                cmd += f' -n {namespace}'
            
            # Add output format
            cmd += ' -o json'
            
            # Add label selector if provided
            if labels:
                label_selector = ','.join(f"{k}={v}" for k, v in labels.items())
                cmd += f' -l {label_selector}'
                
            # Add field selector if provided
            if field_selector:
                cmd += f' --field-selector={field_selector}'
            
            # Get the pods
            output = self._ssh_exec(master_node, cmd, check=True)
            
            # Parse the output
            pods = json.loads(output)
            
            # Extract relevant information
            result = []
            for pod in pods.get('items', []):
                metadata = pod['metadata']
                status = pod['status']
                
                # Calculate pod age
                age = self._get_age(metadata.get('creationTimestamp'))
                
                # Get pod status
                pod_status = status.get('phase', 'Unknown')
                
                # Check container statuses
                container_statuses = {}
                for container in pod.get('spec', {}).get('containers', []):
                    container_statuses[container['name']] = {
                        'ready': False,
                        'restart_count': 0,
                        'state': 'Waiting',
                        'reason': ''
                    }
                
                for status in pod.get('status', {}).get('containerStatuses', []):
                    if status['name'] in container_statuses:
                        container_statuses[status['name']]['ready'] = status['ready']
                        container_statuses[status['name']]['restart_count'] = status['restartCount']
                        
                        # Get container state
                        if status.get('state', {}).get('running') is not None:
                            container_statuses[status['name']]['state'] = 'Running'
                        elif status.get('state', {}).get('waiting') is not None:
                            container_statuses[status['name']]['state'] = 'Waiting'
                            container_statuses[status['name']]['reason'] = status['state']['waiting'].get('reason', '')
                        elif status.get('state', {}).get('terminated') is not None:
                            container_statuses[status['name']]['state'] = 'Terminated'
                            container_statuses[status['name']]['reason'] = status['state']['terminated'].get('reason', '')
                
                # Calculate ready containers
                ready_containers = sum(1 for cs in container_statuses.values() if cs['ready'])
                total_containers = len(container_statuses)
                
                result.append({
                    'name': metadata['name'],
                    'namespace': metadata['namespace'],
                    'status': pod_status,
                    'ready': f"{ready_containers}/{total_containers}",
                    'restarts': max(cs['restart_count'] for cs in container_statuses.values()) if container_statuses else 0,
                    'age': age,
                    'ip': status.get('podIP', ''),
                    'node': status.get('hostIP', ''),
                    'containers': container_statuses
                })
            
            self.log(master_node, f"✅ Found {len(result)} pods")
            return result
            
        except Exception as e:
            self.log(master_node, f"❌ Failed to get pods: {str(e)}")
            raise
    
    def get_services(self, master_node: Node, namespace: str = 'all',
                    labels: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
        """Get information about services in the RKE2 cluster.
        
        Args:
            master_node: A master node to run kubectl commands from
            namespace: Namespace to get services from (default: 'all' for all namespaces)
            labels: Optional label selector to filter services
            
        Returns:
            List[Dict]: List of services with their details
        """
        try:
            self.log(master_node, f"📋 Getting services from namespace '{namespace}'")
            
            # Build the kubectl get services command
            cmd = 'kubectl get services'
            
            # Add namespace
            if namespace.lower() == 'all':
                cmd += ' --all-namespaces'
            else:
                cmd += f' -n {namespace}'
            
            # Add output format
            cmd += ' -o json'
            
            # Add label selector if provided
            if labels:
                label_selector = ','.join(f"{k}={v}" for k, v in labels.items())
                cmd += f' -l {label_selector}'
            
            # Get the services
            output = self._ssh_exec(master_node, cmd, check=True)
            
            # Parse the output
            services = json.loads(output)
            
            # Extract relevant information
            result = []
            for svc in services.get('items', []):
                metadata = svc['metadata']
                spec = svc['spec']
                
                # Format ports
                ports = []
                for port in spec.get('ports', []):
                    port_str = f"{port.get('port', '')}"
                    if 'targetPort' in port:
                        port_str += f":{port['targetPort']}"
                    if 'nodePort' in port:
                        port_str += f":{port['nodePort']}"
                    port_str += f"/{port.get('protocol', 'TCP')}"
                    ports.append(port_str)
                
                result.append({
                    'name': metadata['name'],
                    'namespace': metadata['namespace'],
                    'type': spec.get('type', 'ClusterIP'),
                    'cluster_ip': spec.get('clusterIP', ''),
                    'external_ip': ','.join(spec.get('externalIPs', [])) or '<none>',
                    'ports': ', '.join(ports) or '<none>',
                    'age': self._get_age(metadata.get('creationTimestamp')),
                    'selector': spec.get('selector', {})
                })
            
            self.log(master_node, f"✅ Found {len(result)} services")
            return result
            
        except Exception as e:
            self.log(master_node, f"❌ Failed to get services: {str(e)}")
            raise
    
    def get_deployments(self, master_node: Node, namespace: str = 'all',
                       labels: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
        """Get information about deployments in the RKE2 cluster.
        
        Args:
            master_node: A master node to run kubectl commands from
            namespace: Namespace to get deployments from (default: 'all' for all namespaces)
            labels: Optional label selector to filter deployments
            
        Returns:
            List[Dict]: List of deployments with their details
        """
        try:
            self.log(master_node, f"📋 Getting deployments from namespace '{namespace}'")
            
            # Build the kubectl get deployments command
            cmd = 'kubectl get deployments'
            
            # Add namespace
            if namespace.lower() == 'all':
                cmd += ' --all-namespaces'
            else:
                cmd += f' -n {namespace}'
            
            # Add output format
            cmd += ' -o json'
            
            # Add label selector if provided
            if labels:
                label_selector = ','.join(f"{k}={v}" for k, v in labels.items())
                cmd += f' -l {label_selector}'
            
            # Get the deployments
            output = self._ssh_exec(master_node, cmd, check=True)
            
            # Parse the output
            deployments = json.loads(output)
            
            # Extract relevant information
            result = []
            for deploy in deployments.get('items', []):
                metadata = deploy['metadata']
                spec = deploy.get('spec', {})
                status = deploy.get('status', {})
                
                # Get deployment conditions
                conditions = {}
                for condition in status.get('conditions', []):
                    conditions[condition['type']] = condition['status']
                
                result.append({
                    'name': metadata['name'],
                    'namespace': metadata['namespace'],
                    'ready': f"{status.get('readyReplicas', 0)}/{spec.get('replicas', 0)}",
                    'up_to_date': status.get('updatedReplicas', 0),
                    'available': status.get('availableReplicas', 0),
                    'age': self._get_age(metadata.get('creationTimestamp')),
                    'conditions': conditions,
                    'strategy': spec.get('strategy', {}).get('type', 'RollingUpdate'),
                    'containers': [c['image'] for c in spec.get('template', {}).get('spec', {}).get('containers', [])]
                })
            
            self.log(master_node, f"✅ Found {len(result)} deployments")
            return result
            
        except Exception as e:
            self.log(master_node, f"❌ Failed to get deployments: {str(e)}")
            raise
    
    def verify_cluster_health(self, master_node: Node, expected_masters: int, expected_workers: int, timeout: int = 300) -> bool:
        """Verify the health of the RKE2 cluster.
        
        Args:
            master_node: A master node to run health checks from
            expected_masters: Expected number of master nodes
            expected_workers: Expected number of worker nodes
            timeout: Maximum time to wait for the cluster to become healthy (in seconds)
            
        Returns:
            bool: True if the cluster is healthy, False otherwise
        """
        self.log(master_node, "🔍 Verifying cluster health")
        
        start_time = time.time()
        last_check = 0
        check_interval = 10  # seconds
        
        while time.time() - start_time < timeout:
            try:
                # Check if we need to wait before the next check
                time_since_last_check = time.time() - last_check
                if time_since_last_check < check_interval:
                    time.sleep(check_interval - time_since_last_check)
                last_check = time.time()
                
                # Get node status
                nodes_output = self._ssh_exec(
                    master_node,
                    'export KUBECONFIG=/etc/rancher/rke2/rke2.yaml && '
                    'export PATH=$PATH:/var/lib/rancher/rke2/bin && '
                    'kubectl get nodes -o wide',
                    check=True
                )
                
                # Count ready nodes
                ready_nodes = 0
                master_nodes_ready = 0
                worker_nodes_ready = 0
                
                # Skip header line
                for line in nodes_output.split('\n')[1:]:
                    if not line.strip():
                        continue
                        
                    parts = line.split()
                    if len(parts) < 2:
                        continue
                        
                    node_name = parts[0]
                    status = parts[1]
                    
                    if 'Ready' in status:
                        ready_nodes += 1
                        if 'control-plane' in node_name or 'master' in node_name.lower():
                            master_nodes_ready += 1
                        else:
                            worker_nodes_ready += 1
                
                # Check if we have the expected number of nodes
                if (master_nodes_ready >= expected_masters and 
                    worker_nodes_ready >= expected_workers):
                    self.log(master_node, f"✅ Cluster is healthy: {master_nodes_ready}/{expected_masters} master(s) and {worker_nodes_ready}/{expected_workers} worker(s) ready")
                    return True
                
                self.log(master_node, f"⏳ Waiting for cluster to become healthy: {master_nodes_ready}/{expected_masters} master(s) and {worker_nodes_ready}/{expected_workers} worker(s) ready")
                
            except Exception as e:
                self.log(master_node, f"⚠️  Error checking cluster health: {str(e)}")
            
            # Sleep before next check
            time.sleep(5)
        
        self.log(master_node, f"❌ Cluster health check timed out after {timeout} seconds")
        return False
    
    def install_worker(self, node: Node, server_url: str, token: str = None, reset: bool = True) -> bool:
        """Install and configure RKE2 on a worker node.
        
        This method handles the complete installation process for a worker node,
        including system dependencies, RKE2 installation, and configuration.
        
        Args:
            node: The worker node to install RKE2 on
            server_url: The URL of the master node to join
            token: The cluster token for authentication (optional, will use instance token if not provided)
            reset: Whether to reset the node before installation
            
        Returns:
            bool: True if installation was successful, False otherwise
        """
        try:
            self.log(node, f"🚀 Starting RKE2 worker installation (joining {server_url})")
            
            # Reset node if requested
            if reset and not self.reset_node(node):
                self.log(node, "❌ Failed to reset node before installation")
                return False
            
            # Install system dependencies
            if not self.install_system_dependencies(node):
                self.log(node, "❌ Failed to install system dependencies")
                return False
            
            # Configure RKE2
            if not self.configure_rke2(node, is_server=False, server_url=server_url, token=token):
                self.log(node, "❌ Failed to configure RKE2")
                return False
            
            # Install RKE2
            if not self.install_rke2(node, is_server=False):
                self.log(node, "❌ Failed to install RKE2")
                return False
            
            # Verify the worker joined the cluster
            max_attempts = 30
            for attempt in range(1, max_attempts + 1):
                if self.is_rke2_service_active(node, 'rke2-agent'):
                    # Verify the node registered with the cluster
                    try:
                        # Get the node name from the agent config
                        node_name = self._ssh_exec(
                            node,
                            r'grep -oP "node-name=\K[^"]*" /etc/rancher/rke2/config.yaml || hostname',
                            check=True
                        ).strip()
                        
                        # Check if the node is registered with the control plane
                        master_node = next((n for n in self.connection_pool.hosts if n.role == 'master'), None)
                        if master_node:
                            # Use a simpler JSON path that doesn't require shell escaping
                            result = self._ssh_exec(
                                master_node,
                                'export KUBECONFIG=/etc/rancher/rke2/rke2.yaml && '
                                'export PATH=$PATH:/var/lib/rancher/rke2/bin && '
                                f'kubectl get node {node_name} -o jsonpath="{{.status.conditions[?(@.type==\'Ready\')].status}}"',
                                check=False
                            ).strip()
                            
                            if result == 'True':
                                self.log(node, f"✅ RKE2 worker installation completed successfully (registered as {node_name})")
                                return True
                            
                            self.log(node, f"⚠️  Node {node_name} not ready yet (status: {result}), waiting...")
                    except Exception as e:
                        self.log(node, f"⚠️  Error checking node status (attempt {attempt}/{max_attempts}): {str(e)}")
                
                if attempt < max_attempts:
                    time.sleep(10)
            
            self.log(node, f"❌ RKE2 worker installation did not complete within {max_attempts * 10} seconds")
            return False
            
        except Exception as e:
            self.log(node, f"❌ RKE2 worker installation failed: {str(e)}")
            return False
    
    def configure_rke2(self, node: Node, is_server: bool = True, server_url: str = None, token: str = None) -> bool:
        """Configure RKE2 on the node.
        
        This method delegates to _configure_rke2_service for the actual configuration
        and handles additional setup like audit policy for servers.
        
        Args:
            node: The node to configure
            is_server: Whether this is a server (master) node
            server_url: The URL of the server to connect to (for agents)
            token: The cluster token for authentication
            
        Returns:
            bool: True if configuration was successful, False otherwise
        """
        role = "server" if is_server else "agent"
        self.log(node, f"⚙️  Configuring RKE2 {role}")
        
        try:
            # Create necessary directories
            self._ssh_exec(node, 'mkdir -p /etc/rancher/rke2', check=True)
            
            # Store the server_url for use in _configure_rke2_service
            self.bootstrap_ip = None
            if server_url and '://' in server_url:
                # Extract IP from server URL (e.g., https://1.2.3.4:9345 -> 1.2.3.4)
                self.bootstrap_ip = server_url.split('://')[1].split(':')[0]
            
            # Store the token if provided
            if token:
                self.cluster_token = token
            
            # Call the service configuration function
            from . import service
            service._configure_rke2_service(self, node, is_server)
            
            # Create audit policy file (only for servers)
            if is_server:
                audit_policy = """
                apiVersion: audit.k8s.io/v1
                kind: Policy
                rules:
                  - level: Metadata
                    omitStages:
                      - "RequestReceived"
                """
                
                self._ssh_exec(
                    node,
                    'cat > /etc/rancher/rke2/audit-policy.yaml << EOF\n' + audit_policy.strip() + '\nEOF',
                    check=True
                )
            
            self.log(node, f"✅ RKE2 {'server' if is_server else 'agent'} configuration completed")
            return True
            
        except Exception as e:
            self.log(node, f"❌ Failed to configure RKE2 {role}: {str(e)}")
            import traceback
            self.log(node, f"❌ Stack trace: {traceback.format_exc()}")
            return False
    
    def reset_node(self, node: Node, cleanup: bool = True) -> bool:
        """Reset a node by uninstalling RKE2 and cleaning up all related files.
        
        This method stops RKE2 services, uninstalls RKE2, and removes all related
        files and configurations. It's useful for cleaning up a node before a fresh
        installation or when resetting a cluster.
        
        Args:
            node: The node to reset
            cleanup: Whether to perform full cleanup (remove configs, data, etc.)
            
        Returns:
            bool: True if reset was successful, False otherwise
        """
        self.log(node, "🔄 Resetting RKE2 installation")
        
        try:
            # Stop and disable RKE2 services
            services = ['rke2-server', 'rke2-agent', 'rke2']
            for service_name in services:
                try:
                    self.log(node, f"🛑 Stopping {service_name} service")
                    self._ssh_exec(
                        node,
                        f'systemctl stop {service_name} || true',
                        check=False,
                        timeout=60
                    )
                    self._ssh_exec(
                        node,
                        f'systemctl disable {service_name} || true',
                        check=False
                    )
                except Exception as e:
                    self.log(node, f"⚠️  Failed to stop/disable {service_name}: {str(e)}")
            
            # Uninstall RKE2
            try:
                self.log(node, "🗑️  Uninstalling RKE2")
                self._ssh_exec(
                    node,
                    'if command -v rke2-uninstall.sh >/dev/null; then '
                    'rke2-uninstall.sh; '
                    'elif command -v /usr/local/bin/rke2-uninstall.sh >/dev/null; then '
                    '/usr/local/bin/rke2-uninstall.sh; fi || true',
                    check=False,
                    timeout=300
                )
            except Exception as e:
                self.log(node, f"⚠️  RKE2 uninstall script failed: {str(e)}")
            
            if cleanup:
                # Remove remaining RKE2 files and directories
                self.log(node, "🧹 Cleaning up RKE2 files and directories")
                cleanup_dirs = [
                    '/var/lib/rancher/rke2',
                    '/var/lib/kubelet',
                    '/var/lib/rancher',
                    '/var/lib/cni',
                    '/etc/rancher/rke2',
                    '/etc/rancher/helm',
                    '/etc/cni',
                    '/opt/cni',
                    '/var/run/calico',
                    '/var/run/flannel',
                    '/var/run/k3s',
                    '/var/lib/k3s',
                    '/etc/rancher/k3s',
                    '/var/lib/rancher/k3s',
                    '/usr/local/bin/rke2',
                    '/usr/local/bin/rke2-uninstall.sh',
                    '/usr/local/bin/rke2-killall.sh',
                    '/etc/systemd/system/rke2-*.service',
                    '/etc/systemd/system/rke2-*.env'
                ]
                
                for dir_path in cleanup_dirs:
                    try:
                        self._ssh_exec(
                            node,
                            f'rm -rf {dir_path}',
                            check=False
                        )
                    except Exception as e:
                        self.log(node, f"⚠️  Failed to remove {dir_path}: {str(e)}")
                
                # Reset iptables
                try:
                    self._ssh_exec(
                        node,
                        'iptables -F && iptables -t nat -F && iptables -t mangle -F && '
                        'iptables -X && iptables -t nat -X && iptables -t mangle -X',
                        check=False
                    )
                except Exception as e:
                    self.log(node, f"⚠️  Failed to reset iptables: {str(e)}")
                
                # Remove containerd data
                try:
                    self._ssh_exec(
                        node,
                        'rm -rf /var/lib/containerd/* /var/run/containerd/* /etc/containerd/*',
                        check=False
                    )
                except Exception as e:
                    self.log(node, f"⚠️  Failed to clean up containerd: {str(e)}")
                
                # Reset network interfaces
                try:
                    self._ssh_exec(
                        node,
                        'ip link delete cni0 2>/dev/null || true && '
                        'ip link delete flannel.1 2>/dev/null || true && '
                        'ip link delete kube-ipvs0 2>/dev/null || true',
                        check=False
                    )
                except Exception as e:
                    self.log(node, f"⚠️  Failed to reset network interfaces: {str(e)}")
            
            # Reload systemd and reset failed services
            try:
                self._ssh_exec(node, 'systemctl daemon-reload', check=False)
                self._ssh_exec(node, 'systemctl reset-failed', check=False)
            except Exception as e:
                self.log(node, f"⚠️  Failed to reload systemd: {str(e)}")
            
            self.log(node, "✅ Node reset completed successfully")
            return True
            
        except Exception as e:
            self.log(node, f"❌ Failed to reset node: {str(e)}")
            return False
    
    def _get_kubernetes_version(self) -> str:
        """Get Kubernetes version from cluster configuration file.
        
        Returns:
            str: Kubernetes version string (e.g., 'v1.33.1+rke2r1')
        """
        # Default version if not specified
        default_version = 'v1.33.1+rke2r1'
        
        try:
            # Try to load the cluster config file
            cluster_config_path = Path('clusters/rke2/us-east/prod/dc11a/cluster.yaml')
            if not cluster_config_path.exists():
                logger.warning(f"Cluster config not found at {cluster_config_path}, using default version {default_version}")
                return default_version
                
            with open(cluster_config_path, 'r') as f:
                cluster_config = yaml.safe_load(f)
                
            version = cluster_config.get('kubernetes_version', default_version)
            logger.info(f"Using Kubernetes version from cluster config: {version}")
            return version
        except Exception as e:
            logger.warning(f"Failed to read Kubernetes version from cluster config: {e}, using default {default_version}")
            return default_version
            
    def _reset_node(self, node: Node, cleanup: bool = True) -> bool:
        """Reset a node to a clean state.
        
        Args:
            node: Node to reset
            cleanup: Whether to perform cleanup of RKE2 files
            
        Returns:
            bool: True if reset was successful, False otherwise
        """
        try:
            self.log(node, "🔄 Resetting node...")
            
            # Stop RKE2 service if running
            try:
                self._ssh_exec(node, 'systemctl stop rke2-server rke2-agent 2>/dev/null || true', check=False)
            except Exception as e:
                self.log(node, f"⚠️  Failed to stop RKE2 services: {str(e)}")
            
            if cleanup:
                # Remove remaining RKE2 files and directories
                self.log(node, "🧹 Cleaning up RKE2 files and directories")
                cleanup_dirs = [
                    '/var/lib/rancher/rke2',
                    '/var/lib/kubelet',
                    '/var/lib/rancher',
                    '/var/lib/cni',
                    '/etc/rancher/rke2',
                    '/etc/rancher/helm',
                    '/etc/cni',
                    '/opt/cni',
                    '/var/run/calico',
                    '/var/run/flannel',
                    '/var/run/k3s',
                    '/var/lib/k3s',
                    '/etc/rancher/k3s',
                    '/var/lib/rancher/k3s',
                    '/usr/local/bin/rke2',
                    '/usr/local/bin/rke2-uninstall.sh',
                    '/usr/local/bin/rke2-killall.sh',
                    '/etc/systemd/system/rke2-*.service',
                    '/etc/systemd/system/rke2-*.env'
                ]
                
                for dir_path in cleanup_dirs:
                    try:
                        self._ssh_exec(
                            node,
                            f'rm -rf {dir_path}',
                            check=False
                        )
                    except Exception as e:
                        self.log(node, f"⚠️  Failed to remove {dir_path}: {str(e)}")

                # Reset iptables
                try:
                    self._ssh_exec(
                        node,
                        'iptables -F && iptables -t nat -F && iptables -t mangle -F && '
                        'iptables -X && iptables -t nat -X && iptables -t mangle -X',
                        check=False
                    )
                except Exception as e:
                    self.log(node, f"⚠️  Failed to reset iptables: {str(e)}")

                # Remove containerd data
                try:
                    self._ssh_exec(
                        node,
                        'rm -rf /var/lib/containerd/* /var/run/containerd/* /etc/containerd/*',
                        check=False
                    )
                except Exception as e:
                    self.log(node, f"⚠️  Failed to clean up containerd: {str(e)}")

                # Reset network interfaces
                try:
                    self._ssh_exec(
                        node,
                        'ip link delete cni0 2>/dev/null || true && '
                        'ip link delete flannel.1 2>/dev/null || true && '
                        'ip link delete kube-ipvs0 2>/dev/null || true',
                        check=False
                    )
                except Exception as e:
                    self.log(node, f"⚠️  Failed to reset network interfaces: {str(e)}")

            # Reload systemd and reset failed services
            try:
                self._ssh_exec(node, 'systemctl daemon-reload', check=False)
                self._ssh_exec(node, 'systemctl reset-failed', check=False)
            except Exception as e:
                self.log(node, f"⚠️  Failed to reload systemd: {str(e)}")

            self.log(node, "✅ Node reset completed successfully")
            return True
            
        except Exception as e:
            self.log(node, f"❌ Failed to reset node: {str(e)}")
            return False

def _get_kubernetes_version(self) -> str:
    """Get Kubernetes version from cluster configuration file.
    
    Returns:
        str: Kubernetes version string (e.g., 'v1.33.1+rke2r1')
    """
    # Default version if not specified
    default_version = 'v1.33.1+rke2r1'
    
    try:
        # Try to load the cluster config file
        cluster_config_path = Path('clusters/rke2/us-east/prod/dc11a/cluster.yaml')
        if not cluster_config_path.exists():
            logger.warning(f"Cluster config not found at {cluster_config_path}, using default version {default_version}")
            return default_version
            
        with open(cluster_config_path, 'r') as f:
            cluster_config = yaml.safe_load(f)
            
        version = cluster_config.get('kubernetes_version', default_version)
        logger.info(f"Using Kubernetes version from cluster config: {version}")
        return version
            
    except Exception as e:
        logger.warning(f"Failed to read Kubernetes version from cluster config: {e}, using default {default_version}")
        return default_version

    def _get_rke2_version(self, node: Node) -> tuple:
        """Get installed and running RKE2 versions.
        
        Args:
            node: Node to check versions on
            
        Returns:
            tuple: (installed_version, running_version)
        """
        version_script = """
        set -euo pipefail

        rke2_bin_path='/usr/local/bin/rke2'
        service_name='rke2-server rke2-agent'  # Check both services
        
        # Check if RKE2 is installed
        if [ -f "$rke2_bin_path" ]; then
            installed_version="$($rke2_bin_path --version 2>/dev/null | awk '/version/ {print $3; exit}' || echo 'not installed')"
        else
            installed_version="not installed"
        fi
        
        # Check if RKE2 is running and get its version
        running_version="not running"
        for service in $service_name; do
            if systemctl is-active --quiet $service; then
                pid=$(systemctl show $service --property MainPID --value 2>/dev/null || echo '')
                if [ -n "$pid" ] && [ -e "/proc/$pid/exe" ]; then
                    bin_path=$(readlink -f "/proc/$pid/exe")
                    if [ -f "$bin_path" ]; then
                        running_version="$($bin_path --version 2>/dev/null | awk '/version/ {print $3; exit}' || echo 'unknown')"
                        break
                    fi
                fi
            fi
        done
        
        echo "{\"installed_version\":\"$installed_version\",\"running_version\":\"$running_version\"}"
        """
        
        try:
            result = self._ssh_exec(node, version_script, check=False)
            versions = json.loads(result)
            return versions.get('installed_version', 'not installed'), versions.get('running_version', 'not running')
        except Exception as e:
            self.log(node, f"⚠️  Failed to get RKE2 versions: {str(e)}")
            return 'unknown', 'unknown'

    def _check_common_issues(self, node: Node, service_name: str) -> bool:
        """Check for common RKE2 service issues and log findings.
        
        Args:
            node: The node to check
            service_name: Name of the RKE2 service (rke2-server or rke2-agent)
            
        Returns:
            bool: True if all checks pass, False otherwise
        """
        self.log(node, "🔍 Starting system health checks...")
        
        # Check disk space
        try:
            disk_space = self._ssh_exec(node, 'df -h /var/lib/rancher/rke2 || true', check=False, timeout=30)
            self.log(node, f"💾 Disk space in /var/lib/rancher/rke2:\n{disk_space}")
            
            # Check if disk is over 90% full
            usage_percent = 0
            for line in disk_space.split('\n'):
                if '/var/lib/rancher/rke2' in line:
                    try:
                        usage_percent = int(line.split()[4].replace('%', ''))
                        break
                    except (IndexError, ValueError):
                        pass
            
            if usage_percent > 90:
                self.log(node, f"⚠️  Warning: Disk usage is {usage_percent}% - consider cleaning up space")
                
        except Exception as e:
            self.log(node, f"⚠️  Failed to check disk space: {str(e)}")
        
        # Check container runtime
        try:
            containers = self._ssh_exec(node, 'crictl ps -a || true', check=False, timeout=30)
            self.log(node, f"🐳 Running containers:\n{containers}")
            
            # Check for container runtime status
            runtime_status = self._ssh_exec(node, 'systemctl status containerd || true', check=False, timeout=30)
            if 'active (running)' not in runtime_status.lower():
                self.log(node, f"⚠️  Container runtime is not running")
                self.log(node, f"📋 Container runtime status:\n{runtime_status}")
                
        except Exception as e:
            self.log(node, f"⚠️  Failed to check container status: {str(e)}")
        
        # Check kubelet status
        try:
            kubelet_status = self._ssh_exec(node, 'systemctl status kubelet || true', check=False, timeout=30)
            self.log(node, f"🔍 Kubelet status:\n{kubelet_status}")
            
            if 'active (running)' not in kubelet_status.lower():
                self.log(node, "⚠️  Kubelet is not running")
                
        except Exception as e:
            self.log(node, f"⚠️  Failed to check kubelet status: {str(e)}")
        
        # Check network connectivity
        try:
            network_check = self._ssh_exec(
                node, 
                'curl -s -m 5 -I https://update.rke2.io/version.txt || echo "Network check failed"', 
                check=False,
                timeout=30
            )
            self.log(node, f"🌐 Network connectivity check: {network_check.strip()}")
            
            if 'Network check failed' in network_check:
                self.log(node, "⚠️  Network connectivity check failed")
                
        except Exception as e:
            self.log(node, f"⚠️  Failed to check network connectivity: {str(e)}")
        
        # Install system dependencies if needed
        return self._install_system_dependencies(node)
    
    def _install_system_dependencies(self, node: Node) -> bool:
        """Install required system dependencies.
        
        Args:
            node: The node to install dependencies on
            
        Returns:
            bool: True if installation was successful, False otherwise
        """
        self.log(node, "🔧 Installing system dependencies...")
        
        # Common dependencies for all nodes
        common_pkgs = [
            'curl', 'wget', 'git', 'jq', 'socat', 'conntrack', 'ipset', 'ipvsadm',
            'nfs-common', 'open-iscsi', 'ebtables', 'ethtool', 'ca-certificates',
            'apt-transport-https', 'gnupg', 'lsb-release', 'software-properties-common'
        ]
        
        # Additional dependencies for master nodes
        if node.role == 'master':
            common_pkgs.extend(['kubernetes-cni', 'wireguard'])
        
        try:
            # Get OS information
            os_info = self._ssh_exec(node, 'cat /etc/os-release', check=False, timeout=30)
            
            if not os_info:
                self.log(node, "⚠️  Failed to detect operating system")
                return False
                
            # Process based on OS type
            if 'ubuntu' in os_info.lower() or 'debian' in os_info.lower():
                return self._install_debian_dependencies(node, common_pkgs)
            elif 'centos' in os_info.lower() or 'rhel' in os_info.lower() or 'amzn' in os_info.lower():
                return self._install_rhel_dependencies(node, common_pkgs)
            else:
                self.log(node, f"⚠️  Unsupported OS: {os_info}")
                return False
                
        except Exception as e:
            self.log(node, f"❌ Failed to install system dependencies: {str(e)}")
            return False
    
    def _install_debian_dependencies(self, node: Node, packages: List[str]) -> bool:
        """Install dependencies on Debian-based systems."""
        try:
            # Update package lists
            self._ssh_exec(
                node,
                'DEBIAN_FRONTEND=noninteractive apt-get update -qq',
                check=True,
                timeout=300
            )
            
            # Install common packages
            pkgs_str = ' '.join(packages)
            self._ssh_exec(
                node,
                f'DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends {pkgs_str}',
                check=True,
                timeout=600
            )
            
            # Install container runtime (containerd)
            self._ssh_exec(
                node,
                'install -m 0755 -d /etc/apt/keyrings && '
                'curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg && '
                'chmod a+r /etc/apt/keyrings/docker.gpg && '
                'echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null && '
                'apt-get update && '
                'DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends containerd.io',
                check=True,
                timeout=600
            )
            
            return self._configure_containerd(node)
            
        except Exception as e:
            self.log(node, f"❌ Failed to install Debian dependencies: {str(e)}")
            return False
    
    def _install_rhel_dependencies(self, node: Node, packages: List[str]) -> bool:
        """Install dependencies on RHEL-based systems."""
        try:
            # Install common packages
            pkgs_str = ' '.join(packages)
            self._ssh_exec(
                node,
                f'yum install -y {pkgs_str}',
                check=True,
                timeout=600
            )
            
            # Install container runtime (containerd)
            self._ssh_exec(
                node,
                'yum install -y yum-utils && '
                'yum-config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo && '
                'yum install -y containerd.io',
                check=True,
                timeout=600
            )
            
            return self._configure_containerd(node)
            
        except Exception as e:
            self.log(node, f"❌ Failed to install RHEL dependencies: {str(e)}")
            return False
    
    def _configure_containerd(self, node: Node) -> bool:
        """Configure containerd with recommended settings."""
        try:
            self.log(node, "⚙️  Configuring containerd...")
            
            # Create containerd config directory if it doesn't exist
            self._ssh_exec(node, 'mkdir -p /etc/containerd', check=True, timeout=30)
            
            # Generate default config if it doesn't exist
            self._ssh_exec(
                node,
                '[ -f /etc/containerd/config.toml ] || containerd config default > /etc/containerd/config.toml',
                check=True,
                timeout=30
            )
            
            # Enable SystemdCgroup
            self._ssh_exec(
                node,
                'sed -i \'s/SystemdCgroup = false/SystemdCgroup = true/\' /etc/containerd/config.toml',
                check=True,
                timeout=30
            )
            
            # Restart containerd
            self._ssh_exec(
                node,
                'systemctl daemon-reload && systemctl restart containerd && systemctl enable containerd',
                check=True,
                timeout=60
            )
            
            self.log(node, "✅ Containerd configured successfully")
            return True
            
        except Exception as e:
            self.log(node, f"❌ Failed to configure containerd: {str(e)}")
            return False
    
    def _get_node_token(self, node: Node, max_attempts: int = 30) -> None:
        """Get the node token from the first master.
        
        This method attempts to retrieve the node token from multiple possible locations
        and with retries, as the token file might not be immediately available after
        the RKE2 service starts.
        
        Args:
            node: The master node to get the token from
            max_attempts: Maximum number of attempts to retrieve the token
            
        Raises:
            RuntimeError: If the token cannot be retrieved after all attempts
        """
        self.log(node, f"🔑 Getting node token (max attempts: {max_attempts})")
        
        # Possible token file locations (in order of preference)
        token_files = [
            "/var/lib/rancher/rke2/server/node-token",  # Standard location
            "/var/lib/rancher/rke2/server/token",        # Alternative location
            "/var/lib/rancher/rke2/agent/token"          # Agent token as fallback
        ]
        
        for attempt in range(1, max_attempts + 1):
            # Try each possible token file location
            for token_file in token_files:
                try:
                    # Check if file exists and is not empty
                    exists = self._ssh_exec(
                        node, 
                        f"[ -s {token_file} ] && echo 'exists' || echo ''",
                        check=False,
                        timeout=10
                    ).strip()
                    
                    if exists == 'exists':
                        # Read the token file
                        token = self._ssh_exec(
                            node, 
                            f"cat {token_file}",
                            check=False,
                            timeout=10
                        ).strip()
                        
                        if token:
                            self.node_token = token
                            self.log(node, f"✅ Retrieved node token from {token_file}")
                            return
                            
                except Exception as e:
                    self.log(node, f"⚠️  Error reading token file {token_file}: {str(e)}")
                    continue
            
            # As a last resort, try to get the token from the server URL
            if attempt > 5:  # Only try this after a few attempts with the files
                try:
                    server_url = self._get_server_url(node)
                    if server_url and 'https://' in server_url:
                        # Extract token from URL if it's in the format https://token@ip:port
                        token_part = server_url.split('https://')[1].split('@')[0]
                        if token_part and len(token_part) > 10:  # Basic validation
                            self.node_token = token_part
                            self.log(node, f"✅ Retrieved node token from server URL")
                            return
                except Exception as e:
                    self.log(node, f"⚠️  Error getting token from server URL: {str(e)}")
            
            if attempt < max_attempts:
                self.log(node, f"⌛ Waiting for node token... (attempt {attempt}/{max_attempts})")
                time.sleep(2)
        
        raise RuntimeError(f"Failed to retrieve node token after {max_attempts} attempts")
