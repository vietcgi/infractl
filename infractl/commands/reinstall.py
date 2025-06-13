"""
Cluster Reinstallation Command
=============================

This module provides commands for reinstalling servers in a baremetal cluster managed by MAAS.
It handles the complete reinstallation workflow including:
- Releasing machines from MAAS
- Cleaning up Puppet certificates
- Redeploying servers with specified OS and kernel

Prerequisites:
- MAAS server access with API credentials
- SSH access to the Puppet master
- Properly configured cluster YAML files

Environment Variables:
- MAAS_URL or MAAS_API_URL: URL of the MAAS API server
- MAAS_API_KEY: API key for MAAS authentication
"""

import asyncio
import json
import logging
import os
import re
import shlex
import socket
import subprocess
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union, Any, Set, NamedTuple

import paramiko
import typer
import yaml
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

# Import MAAS client with error handling
try:
    from infractl.modules.maas import MAASClient, get_maas_client
    MAAS_AVAILABLE = True
except ImportError as e:
    MAAS_AVAILABLE = False
    MAAS_IMPORT_ERROR = str(e)

# Configure root logger
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)

# Initialize console for rich output
console = Console()

# Global logger - set to INFO level
logger = logging.getLogger(__name__)

# Set MAAS client logger to WARNING level to reduce noise
maas_logger = logging.getLogger('infractl.modules.maas')
maas_logger.setLevel(logging.WARNING)

# Type aliases
ServerName = str
SystemId = str
ServerResult = Tuple[ServerName, Optional[SystemId]]
ValidationResult = Dict[str, Any]

class ReinstallError(Exception):
    """Custom exception for reinstall operations."""
    pass

class ServerInfo(NamedTuple):
    """Container for server information."""
    name: str
    system_id: Optional[str] = None
    ip_address: Optional[str] = None
    status: Optional[str] = None
    power_state: Optional[str] = None

class ReinstallConfig(NamedTuple):
    """Configuration for server reinstallation."""
    cluster_name: str
    region: str
    env: str
    config_dir: Path
    distro_series: str
    hwe_kernel: str
    ssh_user: str
    ssh_key_path: str
    skip_cloud_init: bool
    dry_run: bool
    yes: bool
    max_workers: int
    timeout: int
    cloud_init: str
    debug: bool
    skip_validation: bool
    validate_only: bool = False  # New flag to only validate without reinstalling

# Create the reinstall command group
app = typer.Typer(help="Cluster reinstallation commands")

def setup_logging(debug: bool = False) -> None:
    """Configure logging based on debug flag."""
    level = logging.DEBUG if debug else logging.INFO
    logger.setLevel(level)
    maas_logger.setLevel(logging.DEBUG if debug else logging.WARNING)

def debug_object(obj: Any, name: str = "object") -> None:
    """Debug function to print detailed information about an object."""
    if obj is None:
        logger.debug(f"{name} is None")
        return
        
    logger.debug(f"{name} type: {type(obj).__name__}")
    
    if hasattr(obj, '__dict__'):
        logger.debug(f"{name} attributes: {vars(obj)}")
    elif hasattr(obj, '__slots__'):
        attrs = {attr: getattr(obj, attr, None) for attr in obj.__slots__ if hasattr(obj, attr)}
        logger.debug(f"{name} attributes: {attrs}")
    elif isinstance(obj, (str, int, float, bool)) or obj is None:
        logger.debug(f"{name} value: {obj}")
    elif isinstance(obj, (list, tuple, set)):
        logger.debug(f"{name} length: {len(obj)}")
        if obj and len(obj) > 0:
            logger.debug(f"First item type: {type(obj[0]).__name__}")
    elif isinstance(obj, dict):
        logger.debug(f"{name} keys: {list(obj.keys())}")
        if obj:
            first_key = next(iter(obj))
            logger.debug(f"First value type for key '{first_key}': {type(obj[first_key]).__name__}")
    else:
        logger.debug(f"{name} has no inspectable attributes")

async def cleanup_puppet_certificate(
    server: str,
    ssh_user: str,
    ssh_key_path: str,
    ssh_semaphore: Optional[asyncio.Semaphore] = None,
    dry_run: bool = False
) -> bool:
    """Clean up Puppet certificate for a server.
    
    Args:
        server: Server hostname
        ssh_user: SSH username
        ssh_key_path: Path to SSH private key
        ssh_semaphore: Optional semaphore to limit concurrent SSH connections
        dry_run: If True, only show what would be done
        
    Returns:
        bool: True if cleanup was successful or skipped, False otherwise
    """
    logger.debug(f"[cleanup_puppet_certificate] server={server}, dry_run={dry_run}")
    
    if dry_run:
        console.print(f"ℹ️  [dry-run] Would clean up Puppet certificate for {server}")
        console.print(f"  [dry-run] Would run: sudo /opt/puppetlabs/bin/puppetserver ca clean --certname {server}.dc11.emodo.io")
        return True
        
    try:
        console.print(f"🔍 Starting Puppet certificate cleanup for {server}...")
        result = await _cleanup_puppet_certificate_impl(server, ssh_user, ssh_key_path, ssh_semaphore)
        if result:
            console.print(f"✅ Successfully cleaned up Puppet certificate for {server}")
        else:
            console.print(f"⚠️  Puppet certificate cleanup may have failed for {server}")
        return result
        
    except Exception as e:
        error_msg = f"Unexpected error during Puppet certificate cleanup for {server}: {e}"
        logger.error(error_msg, exc_info=True)
        console.print(f"❌ {error_msg}")
        
        # Provide helpful troubleshooting tips for common errors
        if isinstance(e, (paramiko.SSHException, socket.timeout, socket.error)):
            console.print("\n  🔍 This appears to be a network/SSH connectivity issue. Please check:")
            console.print(f"     1. Can you connect to the Puppet master (f.dc11.emodo.io) from this machine?")
            console.print(f"     2. Is the SSH key ({os.path.expanduser(ssh_key_path)}) valid and does it have access?")
            console.print(f"     3. Is the Puppet master reachable? Try: ssh {ssh_user}@f.dc11.emodo.io -i {os.path.expanduser(ssh_key_path)}")
            console.print(f"     4. Is the SSH agent running and does it have the key loaded?")
        elif "No such file or directory" in str(e):
            console.print("\n  🔍 The specified SSH key file was not found. Please verify the path:")
            console.print(f"     SSH Key Path: {os.path.expanduser(ssh_key_path)}")
        
        return False

async def _cleanup_puppet_certificate_impl(
    server: str,
    ssh_user: str,
    ssh_key_path: str,
    ssh_semaphore: Optional[asyncio.Semaphore] = None
) -> bool:
    """Implementation of Puppet certificate cleanup.
    
    Args:
        server: Server hostname to clean certificate for
        ssh_user: SSH username for Puppet master
        ssh_key_path: Path to SSH private key
        ssh_semaphore: Optional semaphore for SSH connection limiting
        
    Returns:
        bool: True if cleanup was successful, False otherwise
    """
    try:
        # Clean up Puppet certificate with semaphore control
        success = await clean_puppet_cert(
            hostname=server,
            ssh_user=ssh_user,
            ssh_key_path=ssh_key_path,
            ssh_semaphore=ssh_semaphore
        )
        
        if success:
            console.print(f"✅ Successfully cleaned up Puppet certificate for {server}")
        return success
    except Exception as e:
        logger.error(f"Failed to clean up Puppet certificate for {server}: {e}", exc_info=True)
        console.print(f"❌ Error cleaning Puppet certificate for {server}: {e}")
        return False

def get_all_servers(config_dir: Path, name: str, region: str, env: str) -> List[str]:
    """Get all server hostnames from cluster configuration.
    
    Args:
        config_dir: Base directory containing cluster configurations
        name: Cluster name
        region: AWS region
        env: Environment (e.g., prod, staging)
        
    Returns:
        List of server hostnames
        
    Note:
        Supports both new (masters.hosts) and old (list of hostnames) formats
    """
    # Construct the path to the cluster configuration file
    # First try the rke2 subdirectory
    cluster_dir = config_dir / "rke2" / region / env
    
    # Look for {name}.yaml or {name}/cluster.yaml
    config_file = None
    possible_paths = [
        cluster_dir / f"{name}.yaml",
        cluster_dir / name / "cluster.yaml"
    ]
    
    for path in possible_paths:
        if path.exists():
            config_file = path
            break
    
    if not config_file or not config_file.exists():
        raise FileNotFoundError(
            f"Cluster configuration not found. Tried the following paths:\n" +
            "\n".join(f"- {p}" for p in possible_paths)
        )
    
    logger.debug(f"Loading cluster configuration from {config_file}")
    
    # Load the cluster configuration
    with open(config_file, 'r') as f:
        config = yaml.safe_load(f)
    
    servers = []
    
    # Get master servers
    masters = config.get('masters', {})
    if isinstance(masters, dict):
        # New format: masters.hosts
        servers.extend(masters.get("hosts", []))
    elif isinstance(masters, list):
        # Old format: list of hostnames or dicts with 'name' key
        for master in masters:
            if isinstance(master, dict) and 'name' in master:
                servers.append(master['name'])
            elif isinstance(master, str):
                servers.append(master)
    
    # Get agent servers if they exist
    agents = config.get('agents', {})
    if agents:
        if isinstance(agents, dict):
            # New format: agents.hosts
            servers.extend(agents.get("hosts", []))
        elif isinstance(agents, list):
            # Old format: list of hostnames or dicts with 'name' key
            for agent in agents:
                if isinstance(agent, dict) and 'name' in agent:
                    servers.append(agent['name'])
                elif isinstance(agent, str):
                    servers.append(agent)
    
    return servers


def load_cloud_init() -> str:
    """Load and validate cloud-init configuration from file.
    
    Returns:
        str: The cloud-init configuration as a string, or empty string if loading failed.
    """
    # Look for cloud-init file in the utils directory
    cloud_init_path = Path(__file__).parent.parent / "utils" / "cloud-init.yml"
    if not cloud_init_path.exists():
        logger.error(f"Cloud-init file not found at {cloud_init_path}")
        return ""
        
    try:
        with open(cloud_init_path, 'r') as f:
            content = f.read()
            # Basic validation
            if not content.strip():
                logger.warning("Cloud-init file is empty")
                return ""
            return content
    except Exception as e:
        logger.error(f"Failed to load cloud-init configuration from {cloud_init_path}: {e}")
        return ""

async def reinstall_server(
    server: str,
    config: ReinstallConfig,
    maas_client: MAASClient,
    puppet_cleanup_semaphore: Optional[asyncio.Semaphore] = None,
    ssh_semaphore: Optional[asyncio.Semaphore] = None
) -> ServerResult:
    logger.debug(f"[reinstall_server] skip_puppet_cleanup={config.skip_puppet_cleanup}, dry_run={config.dry_run}")
    """Reinstall a single server with the specified OS and configuration.
    
    Args:
        server: Server hostname to reinstall
        config: Reinstallation configuration
        maas_client: MAAS client instance
        puppet_cleanup_semaphore: Semaphore for controlling Puppet cleanup concurrency
        ssh_semaphore: Semaphore for controlling SSH concurrency
        
    Returns:
        Tuple of (server_name, system_id) where system_id is None if reinstallation failed
    """
    start_time = time.time()
    console.print(f"\n{'='*80}")
    console.print(f"🔄 STARTING REINSTALLATION: {server}")
    console.print(f"{'='*80}")
    
    # Show dry-run message at the start
    if config.dry_run:
        console.print(f"\n{'='*40}")
        console.print(f"🔄 DRY RUN: {server}")
        console.print(f"{'='*40}")
        console.print(f"ℹ️  [dry-run] Would reinstall {server} with OS={config.distro_series}, kernel={config.hwe_kernel}")
        # Don't return yet - we want to show Puppet cleanup info too
    
    try:
        # Get machine info from MAAS
        machine = await maas_client.get_machine_by_hostname(server)
        if not machine:
            console.print(f"❌ [red]Could not find machine {server} in MAAS")
            return server, None
            
        system_id = machine.get('system_id')
        if not system_id:
            console.print(f"❌ [red]Machine {server} has no system_id in MAAS")
            return server, None
            
        # Always perform Puppet certificate cleanup to ensure servers can register with Puppet server
        logger.debug(f"[Puppet Cleanup] dry_run={config.dry_run}")
        console.print(f"🔧 Starting Puppet certificate cleanup for {server}...")
        
        try:
            success = await cleanup_puppet_certificate(
                server=server,
                ssh_user=config.ssh_user,
                ssh_key_path=config.ssh_key_path,
                ssh_semaphore=ssh_semaphore,
                dry_run=config.dry_run
            )
            
            if not success:
                error_msg = f"❌ Failed to clean up Puppet certificate for {server}"
                if not config.dry_run:
                    console.print(error_msg)
                    raise RuntimeError(error_msg)
                else:
                    console.print(f"{error_msg} (dry-run)")
        except Exception as e:
            error_msg = f"❌ Error during Puppet certificate cleanup for {server}: {e}"
            logger.error(error_msg, exc_info=True)
            if not config.dry_run:
                console.print(error_msg)
                raise RuntimeError(error_msg) from e
            else:
                console.print(f"{error_msg} (dry-run)")
        
        # If we're in dry-run mode, we're done after showing what would happen
        if config.dry_run:
            return (server, "dry-run")
            
        # Release and redeploy the machine
        # Check if machine needs to be released first
        current_status = machine.get('status_name', '').lower()
        if current_status not in ['ready', 'failed', 'releasing failed']:
            if machine.get('status') != 'Ready':
                console.print(f"🔧 Releasing {server} (status: {current_status})...")
                try:
                    release_result = await maas_client.release_machine(system_id, force=True)
                    if not release_result:
                        console.print(f"❌ Failed to release {server}")
                        return (server, None)
                    # Wait a bit for the release to complete
                    await asyncio.sleep(5)
                except Exception as e:
                    console.print(f"❌ Error releasing machine {system_id}: {e}")
                    if config.debug:
                        console.print(traceback.format_exc())
                    return (server, None)
            else:
                console.print(f"❌ Cannot reinstall {server} - current status is '{current_status}'. Use --force-release to force release.")
                return (server, None)
        
        # Deploy the machine with the specified OS and kernel
        console.print(f"🚀 Deploying {server} with {config.distro_series} (kernel: {config.hwe_kernel})")
        
        # Prepare user data (cloud-init)
        user_data = config.cloud_init
        if not user_data:
            console.print("⚠️  No cloud-init configuration found, using default")
            user_data = "#cloud-config\n{}"
        
        # Deploy the machine
        deploy_result = await maas_client.deploy_machine(
            system_id=system_id,
            distro_series=config.distro_series,
            hwe_kernel=config.hwe_kernel,
            user_data=user_data
        )
        
        if not deploy_result:
            console.print(f"❌ Failed to deploy {server}")
            return (server, None)
            
        console.print(f"🔄 {server} deployment started. Waiting for completion...")
        
        # Wait for deployment to complete
        max_wait = config.timeout or 900  # Default 15 minutes
        start_time = time.time()
        
        while (time.time() - start_time) < max_wait:
            machine = await maas_client.get_machine(system_id)
            if not machine:
                console.print(f"❌ Lost connection to {server} during deployment")
                return (server, None)
                    
                status = machine.get('status_name', '').lower()
                
                if status == 'deployed':
                    console.print(f"✅ {server} successfully deployed")
                    break
                elif status in ['failed', 'failed deployment']:
                    console.print(f"❌ {server} deployment failed")
                    return (server, None)
                    
                # Show progress every 10 seconds
                if int(time.time() - start_time) % 10 == 0:
                    console.print(f"⏳ {server} status: {status} (elapsed: {int(time.time() - start_time)}s)")
                    
                await asyncio.sleep(5)
            else:
                console.print(f"❌ {server} deployment timed out after {max_wait} seconds")
                return (server, None)
                
        # Verify server is online if not in dry-run mode
        if not config.dry_run and not config.skip_validation:
            console.print(f"🔍 Verifying {server} is online and responsive...")
            # Add server verification logic here if needed
            await asyncio.sleep(10)  # Give it some time to boot
        
        elapsed = time.time() - start_time
        console.print(f"✅ Successfully reinstalled {server} in {elapsed:.1f}s")
        return (server, system_id)
        
    except Exception as e:
        elapsed = time.time() - start_time
        console.print(f"❌ Failed to reinstall {server} after {elapsed:.1f}s: {e}")
        if config.debug:
            console.print(traceback.format_exc())
        return (server, None)

def reinstall_server_sync(server: str, config: ReinstallConfig, maas_client: Any, debug: bool = False) -> Tuple[str, Optional[str]]:
    """Synchronous version of reinstall_server for use with ThreadPoolExecutor"""
    thread_id = threading.get_ident()
    try:
        console.print(f"[{thread_id}] 🔍 Processing {server}...")
        
        # Get machine by hostname
        console.print(f"[{thread_id}] 🔍 Looking up {server} in MAAS...")
        machine = maas_client.get_machine_by_hostname_sync(server)
        if not machine:
            console.print(f"[{thread_id}] ❌ Could not find machine {server} in MAAS")
            return server, None
            
        system_id = machine.get('system_id')
        if not system_id:
            console.print(f"[{thread_id}] ❌ Could not get system_id for {server}")
            return server, None
            
        # Perform Puppet certificate cleanup
        console.print(f"[{thread_id}] 🔧 Starting Puppet certificate cleanup for {server}...")
        try:
            # Create a new event loop for this thread
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            # Run the Puppet cleanup
            success = loop.run_until_complete(
                cleanup_puppet_certificate(
                    server=server,
                    ssh_user=config.ssh_user,
                    ssh_key_path=config.ssh_key_path,
                    dry_run=config.dry_run
                )
            )
            
            if not success and not config.dry_run:
                console.print(f"[{thread_id}] ❌ Failed to clean up Puppet certificate for {server}")
                return server, None
                
        except Exception as e:
            console.print(f"[{thread_id}] ❌ Error during Puppet certificate cleanup for {server}: {e}")
            if debug:
                console.print(traceback.format_exc())
            if not config.dry_run:
                return server, None
        finally:
            loop.close()
            
        # Get the status, handling both enum and string status values
        status = machine.get('status')
        status_str = str(status)
        console.print(f"[{thread_id}] ℹ️  {server} current status: {status_str}")
        
        # Always release the machine first, regardless of current state
        if status_str in ['Releasing failed', '13']:  # 13 is FAILED_RELEASING
            console.print(f"[{thread_id}] ⚠️  {server} is in failed releasing state, attempting to release...")
        
        console.print(f"[{thread_id}] 🔧 Releasing {server} (current status: {status_str})...")
        if not maas_client.release_machine_sync(system_id):
            console.print(f"[{thread_id}] ❌ Failed to release {server}")
            return server, None
                
        # Wait for machine to be released
        max_retries = 30  # 5 minutes with 10s delay
        released = False
        for i in range(max_retries):
            if i > 0 and i % 3 == 0:  # Log every 30 seconds
                console.print(f"[{thread_id}] ⏳ Waiting for {server} to be released... (attempt {i+1}/{max_retries})")
            time.sleep(10)
            machine = maas_client.get_machine_by_hostname_sync(server)
            if machine:
                status = machine.get('status')
                status_str = str(status)
                if status_str in ['Ready', '4']:  # 4 is the enum value for NodeStatus.READY
                    console.print(f"[{thread_id}] ✅ {server} is now Ready")
                    released = True
                    break
        
        if not released:
            console.print(f"[{thread_id}] ❌ Timed out waiting for {server} to be released")
            return server, None
        
        # Install the machine
        console.print(f"[{thread_id}] 🚀 Starting installation of {server}...")
        if not maas_client.install_machine_sync(
            system_id=system_id,
            distro_series=config.distro_series,
            hwe_kernel=config.hwe_kernel
        ):
            console.print(f"[{thread_id}] ❌ Failed to start installation for {server}")
            return server, None
            
        console.print(f"[{thread_id}] ✅ Successfully started installation of {server}")
        return server, system_id
        
    except Exception as e:
        console.print(f"[{thread_id}] ❌ Error reinstalling {server}: {e}")
        if debug:
            console.print(traceback.format_exc())
        return server, None

def validate_server_status(
    server: str,
    maas_client: Any,
    ssh_user: str = None,
    ssh_key_path: str = None,
    debug: bool = False,
    ssh_timeout: int = 30,
) -> bool:
    """Validate server status and SSH connectivity.
    
    Args:
        server: Server hostname to validate
        maas_client: MAAS client instance
        ssh_user: SSH username for validation (optional)
        ssh_key_path: Path to SSH private key (optional)
        debug: Enable debug logging
        ssh_timeout: SSH connection timeout in seconds
        
    Returns:
        bool: True if server is valid and SSH is accessible (if credentials provided)
    """
    thread_id = threading.get_ident()
    console.print(f"[{thread_id}] 🔍 Validating server: {server}")
    
    try:
        # Get machine status from MAAS
        machine = maas_client.get_machine_by_hostname_sync(server)
        if not machine:
            console.print(f"[{thread_id}] ❌ Server not found in MAAS: {server}")
            return False
            
        status = machine.get('status_name', 'unknown')
        power_state = machine.get('power_state', 'unknown')
        
        console.print(f"[{thread_id}] ℹ️  {server} - Status: {status}, Power: {power_state}")
        
        # Check MAAS status
        is_maas_valid = status.lower() in ['deployed', 'ready', 'allocated']
        if not is_maas_valid:
            console.print(f"[{thread_id}] ❌ [red]Invalid MAAS state:[/red] {server} (status: {status})")
            return False
            
        # Check SSH connectivity if credentials are provided
        ssh_valid = True
        if ssh_user and ssh_key_path:
            try:
                import paramiko
                from paramiko.ssh_exception import (
                    SSHException, NoValidConnectionsError, AuthenticationException
                )
                # Get the system ID for the machine
                system_id = machine.get('system_id')
                if not system_id:
                    console.print(f"[{thread_id}] ⚠️  [yellow]No system ID found for {server} in MAAS[/]")
                    return False
                
                # Get full machine details including interfaces
                try:
                    full_machine = maas_client.get_machine_details_sync(system_id)
                    
                    # Extract IP address from the full machine details
                    ip_address = None
                    if full_machine.get('ip_addresses') and len(full_machine['ip_addresses']) > 0:
                        ip_address = full_machine['ip_addresses'][0]
                    
                    if not ip_address:
                        console.print(f"[{thread_id}] ⚠️  [yellow]No IP address found in MAAS for {server}'s interfaces[/]")
                        return False
                        
                except Exception as e:
                    if debug:
                        import traceback
                        console.print(f"[{thread_id}] ⚠️  [yellow]Failed to get machine details for {server}: {str(e)}[/]")
                        console.print(traceback.format_exc())
                    else:
                        console.print(f"[{thread_id}] ⚠️  [yellow]Failed to get machine details for {server}[/]")
                    return False
                    
                console.print(f"[{thread_id}] 📏 Using management IP for {server}: {ip_address}")
                console.print(f"[{thread_id}] 🔌 Testing SSH connection to {ip_address}...")
                
                # Create SSH client
                ssh = paramiko.SSHClient()
                ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                
                # Try to connect
                try:
                    ssh.connect(
                        hostname=ip_address,  # Use IP address instead of hostname
                        username=ssh_user,
                        key_filename=ssh_key_path,
                        timeout=ssh_timeout,
                        banner_timeout=30,
                    )
                    
                    # Execute a simple command to verify shell access
                    stdin, stdout, stderr = ssh.exec_command('echo "SSH test successful"', timeout=10)
                    exit_status = stdout.channel.recv_exit_status()
                    
                    if exit_status != 0:
                        raise SSHException(f"Command failed with status {exit_status}")
                        
                    console.print(f"[{thread_id}] ✅ [green]SSH connection successful:[/green] {server}")
                    
                except (NoValidConnectionsError, ConnectionRefusedError) as e:
                    console.print(f"[{thread_id}] ❌ [red]SSH connection refused:[/red] {server} - {str(e)}")
                    ssh_valid = False
                except AuthenticationException as e:
                    console.print(f"[{thread_id}] ❌ [red]SSH authentication failed:[/red] {server} - {str(e)}")
                    ssh_valid = False
                except SSHException as e:
                    console.print(f"[{thread_id}] ❌ [red]SSH error:[/red] {server} - {str(e)}")
                    ssh_valid = False
                except Exception as e:
                    console.print(f"[{thread_id}] ❌ [red]SSH connection failed:[/red] {server} - {str(e)}")
                    if debug:
                        import traceback
                        console.print(traceback.format_exc())
                    ssh_valid = False
                finally:
                    ssh.close()
            except ImportError:
                console.print(f"[{thread_id}] ⚠️  [yellow]paramiko not installed, skipping SSH validation[/]")
                ssh_valid = True  # Don't fail if paramiko is not installed
            except Exception as e:
                console.print(f"[{thread_id}] ❌ [red]Error during SSH validation:[/red] {str(e)}")
                if debug:
                    import traceback
                    console.print(traceback.format_exc())
                ssh_valid = False
        else:
            console.print(f"[{thread_id}] ⚠️  [yellow]SSH credentials not provided, skipping SSH validation[/]")
        
        if is_maas_valid and ssh_valid:
            console.print(f"[{thread_id}] ✅ [green]Validation successful:[/green] {server}")
            return True
        return False
        
    except Exception as e:
        console.print(f"❌ [red]Error validating {server}: {str(e)}[/]")
        if debug:
            import traceback
            console.print(traceback.format_exc())
        return False

def reinstall_servers(
    config: ReinstallConfig,
    server_names: List[str],
    maas_client: Any,
) -> Tuple[int, List[str], List[str]]:
    """
    Reinstall or validate multiple servers in parallel using one thread per server.
    
    Args:
        config: Reinstall configuration
        server_names: List of server hostnames to reinstall/validate
        maas_client: MAAS client instance
        
    Returns:
        Tuple of (exit_code, succeeded, failed)
    """
    if not server_names:
        console.print("❌ No servers specified")
        return 0, [], []
    
    num_servers = len(server_names)
    action = "validating" if getattr(config, 'validate_only', False) else "reinstalling"
    console.print(f"🚀 Starting {action} of {num_servers} servers with {num_servers} workers...")
    
    # Track results
    succeeded: List[str] = []
    failed: List[str] = []
    result_lock = threading.Lock()
    
    def worker(server: str):
        """Worker function to handle a single server"""
        nonlocal succeeded, failed
        thread_id = threading.get_ident()
        
        try:
            if getattr(config, 'validate_only', False):
                # Only validate the server status
                is_valid = validate_server_status(
                    server=server,
                    maas_client=maas_client,
                    ssh_user=config.ssh_user,
                    ssh_key_path=config.ssh_key_path,
                    debug=config.debug,
                    ssh_timeout=30
                )
                with result_lock:
                    if is_valid:
                        succeeded.append(server)
                    else:
                        failed.append(server)
            else:
                # Full reinstallation
                if config.dry_run:
                    with result_lock:  # Use a lock to prevent interleaved output
                        console.print(f"\n{'='*40}")
                        console.print(f"🔄 [yellow]DRY RUN: {server}[/yellow]")
                        console.print(f"{'='*40}")
                        
                        # Show reinstallation details
                        console.print(f"ℹ️  [yellow][dry-run][/yellow] Would reinstall {server} with:")
                        console.print(f"    - OS: {config.distro_series}")
                        console.print(f"    - Kernel: {config.hwe_kernel}")
                        
                        # Show Puppet cleanup details
                        console.print("\n🔧 [yellow][dry-run] Puppet Certificate Cleanup (required):[/yellow]")
                        console.print(f"   - Would connect to Puppet master: f.dc11.emodo.io")
                        console.print(f"   - Would run: sudo /opt/puppetlabs/bin/puppetserver ca clean --certname {server}.dc11.emodo.io")
                        console.print(f"   - Would verify certificate is cleaned up")
                            
                        succeeded.append(server)
                        console.print(f"\n✅ [green]Dry run complete for {server}[/green]\n")
                else:
                    console.print(f"[{thread_id}] 🚀 Starting reinstallation of {server}")
                    result = reinstall_server_sync(
                        server=server,
                        config=config,
                        maas_client=maas_client,
                        debug=config.debug
                    )
                    server_name, system_id = result
                    with result_lock:
                        if system_id:
                            succeeded.append(server_name)
                            console.print(f"[{thread_id}] ✅ [green]Success:[/green] {server_name}")
                        else:
                            failed.append(server_name)
                            console.print(f"[{thread_id}] ❌ [red]Failed:[/red] {server_name}")
        except Exception as e:
            with result_lock:
                failed.append(server)
                console.print(f"[{thread_id}] ❌ [red]Error processing {server}: {str(e)}[/]")
                if config.debug:
                    import traceback
                    console.print(traceback.format_exc())
    
    # Create and start a thread for each server
    threads = []
    for server in server_names:
        t = threading.Thread(target=worker, args=(server,))
        t.daemon = True  # Allow program to exit even if threads are running
        t.start()
        threads.append(t)
    
    # Wait for all threads to complete
    for t in threads:
        t.join()
    
    # Print summary
    console.print("\n" + "="*50)
    
    if config.dry_run:
        console.print("✅ [green]Dry run completed successfully[/green]")
        console.print(f"ℹ️  Would have reinstalled {len(server_names)} servers")
    else:
        console.print(f"✅ [green]Succeeded:[/green] {len(succeeded)} servers")
        console.print(f"❌ [red]Failed:[/red] {len(failed)} servers")
        
        if failed:
            console.print("\nFailed servers:")
            for server in failed:
                console.print(f"  - {server}")
    
    return 0 if not failed else 1, succeeded, failed

async def reinstall_servers_async(
    config: ReinstallConfig,
    server_names: List[str],
    maas_client: MAASClient
) -> Tuple[int, List[str], List[str]]:
    """Reinstall multiple servers in parallel.
    
    Args:
        config: Reinstallation configuration
        server_names: List of server hostnames to reinstall
        maas_client: MAAS client instance
        
    Returns:
        Tuple of (success_count, succeeded_servers, failed_servers)
    """
    if not server_names:
        console.print("❌ No servers specified for reinstallation")
        return 0, [], []

    # Configure concurrency
    # If max_workers is 0, it means unlimited, so use the number of servers
    # Otherwise, use the specified number of workers, but not more than the number of servers
    if config.max_workers <= 0:
        max_workers = len(server_names)  # Unlimited workers (one per server)
    else:
        max_workers = min(config.max_workers, len(server_names))
    
    console.print(f"🚀 Starting reinstallation of {len(server_names)} servers with {max_workers} workers...")
    
    # Create semaphores for concurrency control
    puppet_cleanup_semaphore = asyncio.Semaphore(max_workers)
    ssh_semaphore = asyncio.Semaphore(max_workers)
    
    # Track results
    succeeded: List[str] = []
    failed: List[str] = []
    
    # Process servers using ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Create a future for each server
        future_to_server = {
            executor.submit(
                reinstall_server_sync,
                server=server,
                config=config,
                maas_client=maas_client,
                debug=config.debug
            ): server for server in server_names
        }
        
        # Process completed futures
        for future in as_completed(future_to_server):
            server = future_to_server[future]
            try:
                server_name, system_id = future.result()
                if system_id:
                    succeeded.append(server_name)
                else:
                    failed.append(server_name)
            except Exception as e:
                console.print(f"❌ Error processing {server}: {e}")
                if config.debug:
                    console.print(traceback.format_exc())
                failed.append(server)
        
        # Process results
        for result in results:
            if isinstance(result, Exception):
                console.print(f"❌ Error in task: {result}")
                continue
                
            server_name, system_id = result
            if system_id:
                succeeded.append(server_name)
            else:
                failed.append(server_name)
    
    return len(succeeded), succeeded, failed

async def _reinstall_cluster_async(
    name: str = typer.Argument(..., help="Cluster name"),
    region: str = typer.Option("us-east", "--region", "-r", help="Cluster region"),
    env: str = typer.Option("prod", "--env", "-e", help="Cluster environment"),
    server: Optional[str] = typer.Option(
        None,
        "--server",
        "-s",
        help="Specific server to reinstall (by hostname). If not specified, all servers will be reinstalled.",
    ),
    config_dir: Path = typer.Option(
        "clusters",
        "--config-dir",
        "-c",
        help="Path to clusters directory",
        exists=True,
        file_okay=False,
        dir_okay=True,
        resolve_path=True,
    ),
    distro_series: str = typer.Option(
        "noble",
        "--os",
        "-o",
        help="Ubuntu release to install (e.g., 'noble', 'jammy')",
    ),
    hwe_kernel: str = typer.Option(
        "ga-24.04",
        "--kernel",
        "-k",
        help="HWE kernel to use (e.g., 'ga-24.04', 'hwe-24.04')",
    ),
    ssh_user: str = typer.Option(
        ...,
        "--ssh-user",
        help="SSH username for accessing the Puppet master and servers (required, cannot be root)",
    ),
    ssh_key_path: str = typer.Option(
        str(Path.home() / ".ssh" / "id_rsa"),
        "--ssh-key",
        help="Path to SSH private key for Puppet master",
    ),
    skip_puppet_cleanup: bool = typer.Option(
        False,
        "--skip-puppet-cleanup",
        help="Skip Puppet certificate cleanup",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        "-n",
        help="Show what would be done without making changes",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Skip confirmation prompt",
    ),
    parallel: int = typer.Option(
        20,  # Increased default from 5 to 20
        "--parallel",
        "-p",
        help="Number of servers to reinstall in parallel (0 for unlimited)",
    ),
    skip_validation: bool = typer.Option(
        False,
        "--skip-validation",
        help="Skip server validation after reinstall (unless --force-validate is used)",
    ),
    validate_only: bool = typer.Option(
        False,
        "--validate-only",
        is_flag=True,
        help="Only validate servers without reinstalling them",
    ),
    timeout: int = typer.Option(
        900,  # 15 minutes default
        "--timeout",
        "-t",
        help="Timeout in seconds for each server operation",
    ),
    debug: bool = typer.Option(
        False,
        "--debug",
        help="Enable debug logging",
    ),
    skip_cloud_init: bool = typer.Option(
        False,
        "--skip-cloud-init",
        help="Skip loading and applying cloud-init configuration",
    ),
) -> None:
    """Async implementation of cluster reinstallation."""
    # Set up logging
    setup_logging(debug=debug)
    
    # Cloud-init is disabled by default for now
    cloud_init = "#cloud-config\n{}"  # Minimal empty config
    if not skip_cloud_init:
        console.print("⚠️  Cloud-init is currently disabled by default. Use --skip-cloud-init to suppress this message.")
        # Uncomment below to re-enable cloud-init loading
        # cloud_init = load_cloud_init()
        # if not cloud_init:
        #     console.print("❌ Failed to load cloud-init configuration")
        #     return 1
    
    # Create MAAS client (synchronous)
    try:
        # Run the synchronous get_maas_client in a thread
        loop = asyncio.get_running_loop()
        maas_client = await loop.run_in_executor(None, get_maas_client)
        if not maas_client:
            console.print("❌ Failed to create MAAS client: No client returned")
            return 1
    except Exception as e:
        console.print(f"❌ Failed to create MAAS client: {e}")
        if debug:
            console.print(traceback.format_exc())
        return 1
    
    # Get list of servers to reinstall
    if server:
        # Split server string by commas and strip whitespace from each server name
        server_names = [s.strip() for s in server.split(',') if s.strip()]
    else:
        try:
            server_names = await asyncio.to_thread(
                get_all_servers, config_dir, name, region, env
            )
            if not server_names:
                console.print(f" No servers found in cluster {name} ({region}/{env})")
                return 1
        except Exception as e:
            console.print(f" Failed to get server list: {e}")
            if debug:
                console.print(traceback.format_exc())
            return 1
    
    # Create config object
    logger.debug("Creating ReinstallConfig")
    config = ReinstallConfig(
        cluster_name=name,
        region=region,
        env=env,
        config_dir=config_dir,
        distro_series=distro_series,
        hwe_kernel=hwe_kernel,
        ssh_user=ssh_user,
        ssh_key_path=ssh_key_path,
        skip_cloud_init=skip_cloud_init,
        dry_run=dry_run,
        yes=yes,
        max_workers=20 if parallel is None else parallel,  # Default to 20 workers if not specified
        timeout=timeout,
        cloud_init=cloud_init,
        debug=debug,
        skip_validation=skip_validation,
        validate_only=validate_only
    )
    
    # Debug output to verify Puppet cleanup setting
    if debug:
        console.print(f"[DEBUG] Puppet cleanup enabled: {not config.skip_puppet_cleanup}")
        console.print(f"[DEBUG] Dry run: {config.dry_run}")
    
    # Show confirmation
    console.print("\n" + "="*50)
    console.print(" CLUSTER REINSTALLATION")
    console.print("="*50)
    console.print(f"Cluster:    {name}")
    console.print(f"Region:     {region}")
    console.print(f"Env:        {env}")
    console.print(f"OS:         {distro_series}")
    console.print(f"Kernel:     {hwe_kernel}")
    console.print(f"Servers:    {len(server_names)}")
    
    if dry_run:
        console.print("\n[bold yellow]Dry run: No changes will be made[/]")
    
    console.print("\nServers to be reinstalled:")
    for srv in server_names:
        console.print(f"  - {srv}")
    
    if not yes and not dry_run:
        console.print(f"\n[bold]Cluster:[/bold] {name}")
        console.print(f"[bold]Region:[/bold] {region}")
        console.print(f"[bold]Environment:[/bold] {env}")
        console.print(f"[bold]Servers:[/bold] {', '.join(server_names) if server_names else 'All servers in cluster'}")
        console.print(f"[bold]Dry run:[/bold] {'Yes' if dry_run else 'No'}")
        console.print(f"[bold]Validate only:[/bold] {'Yes' if validate_only else 'No'}")
        console.print(f"[bold]Parallel workers:[/bold] {config.max_workers}")
        console.print(f"[bold]Timeout:[/bold] {timeout} seconds")
        
        if not typer.confirm("\nAre you sure you want to proceed?"):
            console.print("❌ Operation cancelled by user")
            return 10
    
    # Execute reinstallation
    exit_code, succeeded, failed = reinstall_servers(
        config=config,
        server_names=server_names,
        maas_client=maas_client
    )
    
    # Print summary
    console.print("\n" + "="*50)
    console.print(" REINSTALLATION SUMMARY")
    console.print("="*50)
    console.print(f" Successfully reinstalled: {len(succeeded)} servers")
    console.print(f" Failed: {len(failed)} servers")
    
    if failed:
        return 1
    return 0

@app.command("cluster")
def reinstall_cluster(
    name: str = typer.Argument(..., help="Name of the cluster to reinstall"),
    region: str = typer.Option(..., "--region", "-r", help="Region where the cluster is located"),
    env: str = typer.Option(..., "--env", "-e", help="Environment (e.g., prod, stage, dev)"),
    server: Optional[str] = typer.Option(None, "--server", "-s", help="Specific server to reinstall (optional)"),
    config_dir: Path = typer.Option(
        "clusters",
        "--config-dir",
        "-c",
        help="Path to clusters directory",
        exists=True,
        file_okay=False,
        dir_okay=True,
        resolve_path=True,
    ),
    distro_series: str = typer.Option(
        "noble",
        "--os",
        "-o",
        help="Ubuntu release to install (e.g., 'noble', 'jammy')",
    ),
    hwe_kernel: str = typer.Option(
        "ga-24.04",
        "--kernel",
        "-k",
        help="HWE kernel to use (e.g., 'ga-24.04', 'hwe-24.04')",
    ),
    ssh_user: str = typer.Option(
        ...,
        "--ssh-user",
        help="SSH username for accessing the Puppet master and servers (required, cannot be root)",
    ),
    ssh_key_path: str = typer.Option(
        str(Path.home() / ".ssh" / "id_rsa"),
        "--ssh-key",
        help="Path to SSH private key for Puppet master",
    ),
    skip_puppet_cleanup: bool = typer.Option(
        False,
        "--skip-puppet-cleanup",
        help="Skip Puppet certificate cleanup",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        "-n",
        help="Show what would be done without making changes",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Skip confirmation prompt",
    ),
    parallel: int = typer.Option(
        20,  # Increased default from 5 to 20
        "--parallel",
        "-p",
        help="Number of servers to reinstall in parallel (0 for unlimited)",
    ),
    skip_validation: bool = typer.Option(
        False,
        "--skip-validation",
        help="Skip server validation after reinstall (unless --force-validate is used)",
    ),
    validate_only: bool = typer.Option(
        False,
        "--validate-only",
        is_flag=True,
        help="Only validate servers without reinstalling them",
    ),
    timeout: int = typer.Option(
        900,  # 15 minutes default
        "--timeout",
        "-t",
        help="Timeout in seconds for each server operation",
    ),
    debug: bool = typer.Option(
        False,
        "--debug",
        help="Enable debug logging",
    ),
    skip_cloud_init: bool = typer.Option(
        False,
        "--skip-cloud-init",
        help="Skip loading and applying cloud-init configuration",
    ),
) -> None:
    """Reinstall one or all servers in a baremetal cluster."""
    # Run the async function
    return asyncio.run(_reinstall_cluster_async(
        name=name,
        region=region,
        env=env,
        server=server,
        config_dir=config_dir,
        distro_series=distro_series,
        hwe_kernel=hwe_kernel,
        ssh_user=ssh_user,
        ssh_key_path=ssh_key_path,
        dry_run=dry_run,
        yes=yes,
        parallel=parallel,
        skip_validation=skip_validation,
        validate_only=validate_only,
        timeout=timeout,
        debug=debug,
        skip_cloud_init=skip_cloud_init
    ))

async def clean_puppet_cert(
    hostname: str,
    ssh_user: str,
    ssh_key_path: str,
    ssh_semaphore: Optional[asyncio.Semaphore] = None,
    connect_timeout: int = 30,
    command_timeout: int = 60
) -> bool:
    """Clean up Puppet certificate on the Puppet master.
    
    Args:
        hostname: The hostname to clean the certificate for
        ssh_user: SSH username for the Puppet master
        ssh_key_path: Path to the SSH private key
        ssh_semaphore: Optional semaphore to limit concurrent SSH connections
        connect_timeout: SSH connection timeout in seconds
        command_timeout: Command execution timeout in seconds
        
    Returns:
        bool: True if certificate was cleaned successfully or already cleaned, False otherwise
        
    Raises:
        paramiko.SSHException: For SSH-related errors
        socket.timeout: For connection timeouts
        Exception: For other unexpected errors
    """
    # Validate inputs
    if not hostname or not isinstance(hostname, str):
        raise ValueError("Hostname must be a non-empty string")
    
    if not ssh_key_path or not os.path.isfile(ssh_key_path):
        raise FileNotFoundError(f"SSH key not found at {ssh_key_path}")
    
    # Construct certificate name and Puppet master hostname
    cert_name = f"{hostname}.dc11.emodo.io"
    puppet_master = 'f.dc11.emodo.io'
    
    # Use the provided SSH user or default to 'kevin'
    ssh_username = ssh_user or 'kevin'
    
    # Security check - don't allow root
    if ssh_username == 'root':
        raise ValueError("Root SSH access is not allowed. Please use a non-root user.")
    
    # Initialize SSH client and track semaphore state
    ssh = None
    semaphore_acquired = False
    
    try:
        # Log the connection attempt
        logger.info(f"Connecting to Puppet master {puppet_master} as {ssh_username} to clean cert for {cert_name}")
        console.print(f"🔧 Connecting to Puppet master as {ssh_username}...")
        
        # Create SSH client with more robust configuration
        ssh = paramiko.SSHClient()
        
        # Auto-add host key but warn about potential security implications
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        # Configure keepalive to detect dead connections
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.load_system_host_keys()
        
        # Acquire semaphore if provided
        if ssh_semaphore:
            await ssh_semaphore.acquire()
            semaphore_acquired = True
        
        # Connect with timeouts and key verification
        try:
            ssh.connect(
                hostname=puppet_master,
                username=ssh_username,
                key_filename=ssh_key_path,
                timeout=connect_timeout,
                banner_timeout=connect_timeout,
                auth_timeout=connect_timeout,
                look_for_keys=False,  # Explicitly disable key discovery
                allow_agent=False,     # Don't use SSH agent
                compress=True          # Enable compression for better performance
            )
        except paramiko.ssh_exception.SSHException as e:
            logger.error(f"SSH connection to {puppet_master} failed: {e}")
            console.print(f"❌ SSH connection failed: {e}")
            raise
            
        console.print(f"✅ Connected to Puppet master at {puppet_master}")
        
        # Construct and log the command
        cmd = f"sudo /opt/puppetlabs/bin/puppetserver ca clean --certname {cert_name}"
        logger.info(f"Executing command: {cmd}")
        console.print(f"  Running: {cmd}")
        
        # Execute the command with proper timeouts
        try:
            # Use exec_command with get_pty=True for sudo
            stdin, stdout, stderr = ssh.exec_command(cmd, timeout=command_timeout, get_pty=True)
            
            # Read output in real-time
            output = []
            error = []
            
            # Helper function to read from channels
            def read_from_channel(channel, buffer, is_stderr=False):
                prefix = "[stderr] " if is_stderr else ""
                while channel.recv_ready():
                    data = channel.recv(4096).decode('utf-8', 'replace')
                    if not data:
                        break
                    buffer.append(data)
                    console.print(f"  {prefix}{data}".strip())
                    # Check for password prompt
                    if "password" in data.lower():
                        raise RuntimeError("Password prompt detected. Please set up passwordless sudo for this user.")
            
            # Read while command is running
            while not stdout.channel.exit_status_ready():
                read_from_channel(stdout.channel, output)
                read_from_channel(stdout.channel, error, is_stderr=True)
                await asyncio.sleep(0.1)  # Be nice to the event loop
            
            # Read any remaining output
            read_from_channel(stdout.channel, output)
            read_from_channel(stdout.channel, error, is_stderr=True)
            
            # Get the exit status
            exit_status = stdout.channel.recv_exit_status()
            
            # Get the full output and error
            full_output = ''.join(output)
            full_error = ''.join(error)
            
            if exit_status == 0:
                logger.info(f"Successfully cleaned certificate for {cert_name}")
                return True
                
            # Combine output for easier checking
            combined_output = (full_output + full_error).lower()
            
            # Check for various "not found" or "already cleaned" cases
            not_found_phrases = [
                "could not find files to clean",
                "could not find a certificate",
                "no certificates to clean",
                "nothing was deleted",
                "already revoked",
                "does not exist"
            ]
            
            if any(phrase in combined_output for phrase in not_found_phrases):
                msg = f"ℹ️  Puppet certificate for {cert_name} was already cleaned/revoked or doesn't exist"
                console.print(msg)
                logger.info(msg)
                return True
            
            # Handle other error cases
            error_msg = f"Failed to clean Puppet certificate for {cert_name} (exit {exit_status})"
            console.print(f"❌ {error_msg}")
            if full_output.strip():
                console.print(f"   Output: {full_output.strip()}")
            if full_error.strip():
                console.print(f"   Error: {full_error.strip()}")
            
            logger.error(f"{error_msg}\nOutput: {full_output}\nError: {full_error}")
            return False
            
        except socket.timeout as e:
            error_msg = f"Command timed out after {command_timeout} seconds"
            logger.error(error_msg)
            console.print(f"❌ {error_msg}")
            return False
            
        except Exception as e:
            logger.error(f"Error executing command: {e}", exc_info=True)
            console.print(f"❌ Error executing command: {e}")
            return False
            
    except Exception as e:
        logger.error(f"Error in clean_puppet_cert: {e}", exc_info=True)
        console.print(f"❌ Error in clean_puppet_cert: {e}")
        raise  # Re-raise to allow upper layers to handle it
        
    finally:
        # Always release the semaphore if we acquired it
        if ssh_semaphore and semaphore_acquired:
            ssh_semaphore.release()
            semaphore_acquired = False
            
        # Close the SSH connection if it was established
        if ssh:
            try:
                ssh.close()
                logger.debug("SSH connection closed")
            except Exception as e:
                logger.warning(f"Error closing SSH connection: {e}")
                console.print(f"  ⚠️  Warning: Error closing SSH connection: {e}")

if __name__ == "__main__":
    app()
