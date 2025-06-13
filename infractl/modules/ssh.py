"""
SSH connection management using native OpenSSH with ControlMaster.
"""
import os
import subprocess
import tempfile
import shutil
import threading
import time
import logging
import paramiko
from pathlib import Path
from typing import Dict, Optional, Any, List, Tuple
from contextlib import contextmanager

logger = logging.getLogger("ssh")

class SSHConnection:
    """SSH connection using native OpenSSH with ControlMaster."""
    
    def __init__(self, host: str, username: str, key_path: str = None, port: int = 22, timeout: int = 60, **kwargs):
        """Initialize SSH connection.
        
        Args:
            host: Remote host to connect to
            username: Username for authentication
            key_path: Path to SSH private key (optional)
            port: SSH port (default: 22)
            timeout: Connection timeout in seconds (default: 30)
            **kwargs: Additional arguments passed to _connect
        """
        self.host = host
        self.username = username
        self.key_path = os.path.expanduser(key_path) if key_path else None
        self.port = port
        self.timeout = timeout
        self.control_path = f"/tmp/ssh_control_{self.username}@{self.host}:{port}"
        self.control_master = None
        self._connect(**kwargs)
    
    def __enter__(self):
        """Context manager entry point."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit point.
        
        Note: We don't close the connection here as it's managed by the ControlMaster.
        The connection will be automatically cleaned up when the pool is closed.
        """
        pass
        
    def open_sftp(self):
        """Return self to maintain compatibility with paramiko's SFTP interface.
        
        Note: This doesn't actually create an SFTP session, but provides a compatible
        interface that will use scp for file transfers.
        
        Returns:
            self: The SSHConnection instance itself
        """
        return self
        
    def put(self, localpath, remotepath, callback=None, confirm=True):
        """Upload a file to the remote host using scp.
        
        This method provides a paramiko-compatible interface for file uploads.
        
        Args:
            localpath: Path to the local file to upload
            remotepath: Path on the remote host to upload to
            callback: Optional callback function (not implemented)
            confirm: Whether to verify the file was transferred (not implemented)
            
        Raises:
            RuntimeError: If the file transfer fails
        """
        try:
            # Use scp to copy the file
            scp_cmd = f'scp -o ControlPath={self.control_path} -P {self.port} {localpath} {self.username}@{self.host}:{remotepath}'
            result = subprocess.run(
                scp_cmd,
                shell=True,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            return
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to upload {localpath} to {self.host}:{remotepath}: {e.stderr}")
            
    def get(self, remotepath, localpath, callback=None):
        """Download a file from the remote host using scp.
        
        This method provides a paramiko-compatible interface for file downloads.
        
        Args:
            remotepath: Path on the remote host to download from
            localpath: Path to save the downloaded file to locally
            callback: Optional callback function (not implemented)
            
        Raises:
            RuntimeError: If the file transfer fails
        """
        try:
            # Use scp to download the file
            scp_cmd = f'scp -o ControlPath={self.control_path} -P {self.port} {self.username}@{self.host}:{remotepath} {localpath}'
            result = subprocess.run(
                scp_cmd,
                shell=True,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            return
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to download {self.host}:{remotepath} to {localpath}: {e.stderr}")
            
    def stat(self, path):
        """Get information about a file or directory on the remote host.
        
        This method provides a paramiko-compatible interface for checking file/directory existence.
        
        Args:
            path: Path to check
            
        Returns:
            dict: Dictionary with file/directory information if it exists
            
        Raises:
            FileNotFoundError: If the path does not exist
        """
        try:
            # Use ls -ld to get file info
            result = self.execute(f'ls -ld {path}')
            if result[0] == 0 and result[1]:
                # Parse the ls output to get file info
                parts = result[1].split()
                if len(parts) >= 8:
                    return {
                        'st_mode': int(parts[0], 8) if len(parts[0]) == 10 else 0o100644,  # Default to regular file
                        'st_uid': int(parts[2]) if parts[2].isdigit() else 0,
                        'st_gid': int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 0,
                        'st_size': int(parts[4]) if len(parts) > 4 and parts[4].isdigit() else 0,
                    }
            # If we got here, the path exists but we couldn't parse the output
            return {}
        except Exception as e:
            # If the command fails, the path doesn't exist
            raise FileNotFoundError(f"Path {path} not found: {str(e)}")
            
    def mkdir(self, path, mode=0o777):
        """Create a directory on the remote host.
        
        Args:
            path: Path of the directory to create
            mode: Permissions for the new directory (not implemented)
            
        Raises:
            RuntimeError: If the directory creation fails
        """
        try:
            self.execute(f'mkdir -p {path}')
        except Exception as e:
            raise RuntimeError(f"Failed to create directory {path}: {str(e)}")
        
    def get_transport(self):
        """Get the underlying transport object. Only allow real transports."""
        # If a real transport cannot be established, raise an error instead of returning DummyTransport
        raise RuntimeError("Failed to establish a real SSH transport. DummyTransport is not allowed in production.")
        
    def exec_command(self, command, get_pty=False, timeout=None):
        """Execute a command on the remote host.
        
        This method provides a paramiko-compatible interface for executing commands
        over SSH using the native SSH client.
        
        Args:
            command: The command to execute
            get_pty: Whether to allocate a pseudo-terminal (ignored for native SSH)
            timeout: Command timeout in seconds (optional)
            
        Returns:
            tuple: (stdin, stdout, stderr) file-like objects
        """
        # For native SSH, we'll just use the execute method and return file-like objects
        # that match paramiko's interface
        class CommandResult:
            def __init__(self, output, error, exit_status):
                self.output = output
                self.error = error
                self.exit_status = exit_status
                self.offset = 0
                
            def read(self, size=-1):
                if size == -1:
                    result = self.output[self.offset:]
                    self.offset = len(self.output)
                    return result
                else:
                    result = self.output[self.offset:self.offset + size]
                    self.offset = min(self.offset + size, len(self.output))
                    return result
                    
            def readline(self, size=-1):
                if '\n' in self.output[self.offset:]:
                    idx = self.output.index('\n', self.offset) + 1
                    result = self.output[self.offset:idx]
                    self.offset = idx
                    return result
                return self.read(size) if size > 0 else self.read()
                
            def readlines(self):
                return self.output[self.offset:].splitlines(keepends=True)
                
            @property
            def channel(self):
                class Channel:
                    def __init__(self, exit_status):
                        self.exit_status = exit_status
                        self.recv_exit_status_called = False
                        
                    def recv_exit_status(self):
                        self.recv_exit_status_called = True
                        return self.exit_status
                        
                    def exit_status_ready(self):
                        return True
                        
                return Channel(self.exit_status)
                
        # Execute the command
        exit_status, stdout, stderr = self.execute(command, timeout=timeout)
        
        # Create file-like objects for the result
        result = CommandResult(stdout, stderr, exit_status)
        
        # Return a tuple that matches paramiko's interface
        return (None, result, CommandResult(stderr, '', 0))
    
    def _connect(self, **kwargs):
        """Establish SSH connection with ControlMaster."""
        try:
            # Create a unique control path for this connection
            self.control_dir = os.path.join(tempfile.gettempdir(), f"ssh_{os.getpid()}")
            os.makedirs(self.control_dir, mode=0o700, exist_ok=True)
            self.control_path = os.path.join(self.control_dir, f"cm_{self.host}")
            
            logger.debug(f"Using control path: {self.control_path}")
            
            # Start ControlMaster if not already running
            if not self._is_control_master_running():
                logger.debug(f"Starting new ControlMaster for {self.username}@{self.host}")
                self._start_control_master()
            else:
                logger.debug(f"Using existing ControlMaster for {self.username}@{self.host}")
                
        except Exception as e:
            logger.error(f"Failed to establish SSH connection to {self.username}@{self.host}: {str(e)}")
            raise
    
    def _is_control_master_running(self) -> bool:
        """Check if ControlMaster is already running."""
        if not os.path.exists(self.control_path):
            logger.debug(f"Control path {self.control_path} does not exist")
            return False
            
        try:
            cmd = [
                'ssh',
                '-o', 'ControlMaster=no',
                '-S', self.control_path,
                '-O', 'check',
                f'{self.username}@{self.host}'
            ]
            logger.debug(f"Checking ControlMaster status: {' '.join(cmd)}")
            
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=10
            )
            
            is_running = "master is running" in (result.stderr or '')
            logger.debug(f"ControlMaster check result: {'running' if is_running else 'not running'}")
            if not is_running and (result.stderr or result.stdout):
                logger.debug(f"SSH check output - stderr: {result.stderr}, stdout: {result.stdout}")
                
            return is_running
            
        except subprocess.TimeoutExpired:
            logger.warning("ControlMaster check timed out")
            return False
        except Exception as e:
            logger.warning(f"Error checking ControlMaster status: {str(e)}")
            return False
    
    def _start_control_master(self):
        """Verify SSH connection is working.
        
        This method verifies that we can connect to the remote host but doesn't use ControlMaster.
        We'll use direct connections for each command instead.
        """
        # Test SSH connection with a simple command
        test_cmd = [
            'ssh',
            '-v',
            '-o', 'BatchMode=yes',
            '-o', 'ConnectTimeout=10',
            '-o', 'StrictHostKeyChecking=no',
            '-o', 'UserKnownHostsFile=/dev/null',
            '-o', 'ServerAliveInterval=5',
            '-o', 'ServerAliveCountMax=3',
            '-o', 'TCPKeepAlive=yes',
            '-p', str(self.port),
            f'{self.username}@{self.host}',
            'echo', 'SSH_TEST_CONNECTION_SUCCESS'
        ]
        
        if self.key_path:
            test_cmd.extend(['-i', os.path.expanduser(self.key_path)])
        
        logger.info(f"Testing SSH connection to {self.username}@{self.host}:{self.port}")
        
        try:
            # Run test connection
            test_result = subprocess.run(
                test_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=30
            )
            
            if 'SSH_TEST_CONNECTION_SUCCESS' not in test_result.stdout:
                logger.error(f"SSH test connection failed. Exit code: {test_result.returncode}")
                logger.error(f"STDOUT: {test_result.stdout}")
                logger.error(f"STDERR: {test_result.stderr}")
                raise RuntimeError(f"SSH test connection to {self.host} failed")
            
            logger.info("SSH test connection successful")
            
        except subprocess.TimeoutExpired:
            error_msg = "SSH test connection timed out after 30 seconds"
            logger.error(error_msg)
            raise RuntimeError(error_msg)
        except Exception as e:
            error_msg = f"Unexpected error during SSH test connection: {str(e)}"
            logger.error(error_msg)
            raise RuntimeError(error_msg)
    
    def execute(self, command: str, timeout: int = 300) -> Tuple[int, str, str]:
        """Execute a command over SSH using a direct connection."""
        cmd = [
            'ssh',
            '-T',  # Disable pseudo-terminal allocation
            '-o', 'BatchMode=yes',
            '-o', 'StrictHostKeyChecking=no',
            '-o', 'UserKnownHostsFile=/dev/null',
            '-o', 'ServerAliveInterval=5',
            '-o', 'ServerAliveCountMax=3',
            '-o', 'ConnectTimeout=30',
            '-o', 'ConnectionAttempts=3',
            '-p', str(self.port)
        ]
        
        if self.key_path:
            cmd.extend(['-i', self.key_path])
            
        cmd.extend([
            f'{self.username}@{self.host}',
            command
        ])
        
        try:
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=timeout
            )
            return (result.returncode, result.stdout, result.stderr)
        except subprocess.TimeoutExpired:
            return (255, '', f"Command timed out after {timeout} seconds")
        except Exception as e:
            return (255, '', str(e))
    
    def close(self):
        """Close the SSH connection and clean up."""
        if self.control_path and os.path.exists(self.control_path):
            try:
                subprocess.run([
                    'ssh', '-O', 'exit',
                    '-o', f'ControlPath={self.control_path}',
                    f'{self.username}@{self.host}'
                ], stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
            except Exception:
                pass
            
            try:
                os.unlink(self.control_path)
            except Exception:
                pass
        
        if hasattr(self, 'control_dir') and os.path.exists(self.control_dir):
            try:
                shutil.rmtree(self.control_dir, ignore_errors=True)
            except Exception:
                pass

class ConnectionPool:
    """Thread-safe SSH connection pool using native OpenSSH with ControlMaster."""
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(ConnectionPool, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance
    
    def __init__(self):
        if hasattr(self, '_initialized') and self._initialized:
            return
            
        self.connections: Dict[str, SSHConnection] = {}
        self.lock = threading.RLock()
        self.pool = []  # List to track available connections
        self._initialized = True
    
    def get_connection(self, host: str, username: str, key_path: str, **kwargs):
        """Get a connection from the pool.
        
        Args:
            host: SSH host to connect to
            username: SSH username
            key_path: Path to SSH private key
            **kwargs: Additional connection parameters including:
                - port: SSH port (default: 22)
                - timeout: Connection timeout in seconds (default: 60)
                - Any other parameters supported by SSHConnection
            
        Returns:
            SSHConnection: An active SSH connection
        """
        connection_id = f"{username}@{host}"
        
        with self.lock:
            if connection_id in self.connections:
                try:
                    # Test if connection is still alive
                    self.connections[connection_id].execute("echo test", timeout=5)
                    return self.connections[connection_id]
                except Exception as e:
                    logger.debug(f"Connection test failed, creating new connection: {e}")
                    del self.connections[connection_id]
            
            # Create a new connection
            logger.debug(f"Creating new SSH connection to {connection_id}")
            conn = SSHConnection(host=host, username=username, key_path=key_path, **kwargs)
            self.connections[connection_id] = conn
            return conn
    
    def _create_connection(self, host: str, username: str, key_path: str, **kwargs) -> SSHConnection:
        """Create a new SSH connection.
        
        Args:
            host: SSH host to connect to
            username: SSH username
            key_path: Path to SSH private key
            **kwargs: Additional connection parameters
            
        Returns:
            SSHConnection: A new SSH connection
        """
        return SSHConnection(
            host=host,
            username=username,
            key_path=key_path,
            **kwargs
        )
    
    def close_all(self):
        """Close all connections in the pool."""
        with self.lock:
            for conn in self.connections.values():
                try:
                    # Clean up control master connections safely
                    if not hasattr(conn, 'control_dir') or not conn.control_dir:
                        continue
                        
                    # Ensure we're only removing directories under /tmp or /var/tmp
                    control_dir = str(conn.control_dir)
                    safe_paths = ['/tmp/', '/var/tmp/', tempfile.gettempdir() + os.sep]
                    
                    if not any(control_dir.startswith(p) for p in safe_paths):
                        logger.warning(f"Skipping cleanup of non-temp directory: {control_dir}")
                        continue
                        
                    if os.path.exists(control_dir):
                        logger.debug(f"Cleaning up SSH control directory: {control_dir}")
                        try:
                            # Try to remove individual files first
                            for root, dirs, files in os.walk(control_dir, topdown=False):
                                for name in files:
                                    try:
                                        os.unlink(os.path.join(root, name))
                                    except Exception as e:
                                        logger.debug(f"Failed to remove {os.path.join(root, name)}: {e}")
                                for name in dirs:
                                    try:
                                        os.rmdir(os.path.join(root, name))
                                    except Exception as e:
                                        logger.debug(f"Failed to remove directory {os.path.join(root, name)}: {e}")
                            # Finally, try to remove the directory itself
                            os.rmdir(control_dir)
                        except Exception as e:
                            logger.warning(f"Failed to clean up SSH control directory {control_dir}: {e}")
                            
                except Exception as e:
                    logger.warning(f"Error during SSH connection cleanup: {e}")
                    
            self.connections.clear()
            self.pool = []
    
    def __del__(self):
        """Clean up connections when the pool is destroyed."""
        self.close_all()

# Global instance
ssh_pool = ConnectionPool()

def get_ssh_pool() -> ConnectionPool:
    """Get the global SSH connection pool."""
    return ssh_pool
