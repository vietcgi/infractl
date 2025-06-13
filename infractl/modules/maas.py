"""
MAAS API client module for interacting with MAAS server.
"""
import os
import sys
import asyncio
import concurrent.futures
import json
import logging
import socket
import ssl
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional, Set, Tuple, Union, cast, TypeVar, Callable, Coroutine

# Configure logger at module level
logger = logging.getLogger(__name__)

# Try to import MAAS client with compatibility for different versions
try:
    # Try importing from the standard package name first
    try:
        from maas.client import connect as maas_connect
        from maas.client.enum import NodeStatus
        from maas.client.viscera.machines import Machine
    except ImportError:
        # Fall back to python-libmaas package name
        from libmaas.client import connect as maas_connect
        from libmaas.client.enum import NodeStatus
        from libmaas.client.viscera.machines import Machine
    
    # Check if we need to handle distutils
    try:
        import distutils
    except ImportError:
        # distutils is not available in Python 3.12+, use setuptools as a replacement
        import setuptools
        import warnings
        warnings.warn("distutils not available, using setuptools compatibility layer")
        sys.modules['distutils'] = setuptools._distutils
    
    MAAS_AVAILABLE = True
except ImportError as e:
    # This will only be called if the import fails, so we can safely use logger now
    logger.error(f"Failed to import MAAS client: {e}")
    MAAS_AVAILABLE = False

# Type variables for generic typing
T = TypeVar('T')
F = TypeVar('F', bound=Callable[..., Any])

# Custom exceptions
class MAASError(Exception):
    """Base exception for MAAS client errors."""
    pass

class MAASAuthenticationError(MAASError):
    """Exception raised for authentication errors."""
    pass

class MAASConnectionError(MAASError):
    """Exception raised for connection errors."""
    pass

class MAASObjectNotFoundError(MAASError):
    """Exception raised when a requested object is not found."""
    pass

class MAASClient:
    """Client for interacting with MAAS API."""
    
    # Class-level thread pool executor for all instances
    _executor = ThreadPoolExecutor(max_workers=20, thread_name_prefix="maas_client_thread")
    _executor_lock = Lock()
    
    def __init__(self, url: str, api_key: str, debug: bool = False):
        """Initialize the MAAS client.
        
        Args:
            url: MAAS server URL (e.g., 'http://maas.example.com/MAAS/')
            api_key: MAAS API key (format: 'consumer_key:token_key:secret')
            debug: Enable debug logging
        """
        self.url = url.rstrip('/')
        self.api_key = api_key
        self.debug = debug
        self._client = None
        self._client_lock = Lock()
        self.logger = logging.getLogger(f"{__name__}.MAASClient")
        
        if debug:
            self.logger.setLevel(logging.DEBUG)
            
        # Validate API key format
        try:
            if len(self.api_key.split(':')) != 3:
                raise ValueError("API key must be in format 'consumer_key:token_key:token_secret'")
            self.consumer_key, self.token_key, self.token_secret = self.api_key.split(':')
        except Exception as e:
            raise ValueError(f"Invalid API key format: {e}")
    
    async def get_machine(self, system_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a machine by its system ID.
        
        Args:
            system_id: The system ID of the machine
            
        Returns:
            Dictionary containing machine details if found, None otherwise
        """
        def _get_machine():
            try:
                self._ensure_client()
                machine = None
                for m in self._client.machines.list():
                    if m.system_id == system_id:
                        machine = m
                        break
                        
                if not machine:
                    self.logger.warning(f"Machine {system_id} not found")
                    return None
                    
                # Convert machine object to dict
                machine_dict = {
                    'system_id': machine.system_id,
                    'hostname': getattr(machine, 'hostname', ''),
                    'status': getattr(machine, 'status', None),
                    'status_name': getattr(machine, 'status_name', ''),
                    'power_state': getattr(machine, 'power_state', 'unknown'),
                    'interface_set': getattr(machine, 'interface_set', []),
                    'fqdn': getattr(machine, 'fqdn', ''),
                    'cpu_count': getattr(machine, 'cpu_count', 0),
                    'memory': getattr(machine, 'memory', 0),
                    'osystem': getattr(machine, 'osystem', ''),
                    'distro_series': getattr(machine, 'distro_series', ''),
                    'hwe_kernel': getattr(machine, 'hwe_kernel', None)
                }
                
                self.logger.debug(f"Found machine by ID {system_id}: {machine_dict}")
                return machine_dict
                
            except Exception as e:
                self.logger.error(f"Error getting machine {system_id}: {e}")
                if self.debug:
                    self.logger.debug(traceback.format_exc())
                return None
        
        # Run the synchronous code in a thread
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _get_machine)
            
    async def get_machine_by_hostname(self, hostname: str, max_retries: int = 3, initial_delay: float = 1.0) -> Optional[Dict[str, Any]]:
        """
        Get a machine by its hostname asynchronously using thread pool with retries.
        
        Args:
            hostname: The hostname of the machine to find
            max_retries: Maximum number of retry attempts
            initial_delay: Initial delay between retries in seconds (will be doubled each retry)
            
        Returns:
            Dictionary containing machine details if found, None otherwise
        """
        retry_count = 0
        delay = initial_delay
        loop = asyncio.get_running_loop()
        
        while retry_count < max_retries:
            try:
                # Run the synchronous operation in the thread pool with timeout
                return await asyncio.wait_for(
                    loop.run_in_executor(
                        self._executor,
                        self._get_machine_by_hostname_sync,
                        hostname
                    ),
                    timeout=30  # 30 second timeout for the operation
                )
                
            except asyncio.TimeoutError:
                retry_count += 1
                if retry_count >= max_retries:
                    self.logger.error(f"Timeout getting machine {hostname} after {max_retries} attempts")
                    return None
                
                # Exponential backoff with jitter
                wait_time = min(delay * (2 ** (retry_count - 1)), 30)  # Cap at 30 seconds
                self.logger.warning(
                    f"Timeout getting machine {hostname}, "
                    f"retrying in {wait_time:.1f}s (attempt {retry_count + 1}/{max_retries})"
                )
                await asyncio.sleep(wait_time)
                
            except Exception as e:
                retry_count += 1
                if retry_count >= max_retries:
                    self.logger.error(f"Failed to get machine {hostname} after {max_retries} attempts: {e}")
                    if self.debug:
                        self.logger.debug(traceback.format_exc())
                    return None
                
                # Exponential backoff with jitter
                wait_time = min(delay * (2 ** (retry_count - 1)), 30)  # Cap at 30 seconds
                self.logger.warning(
                    f"Error getting machine {hostname}: {e}, "
                    f"retrying in {wait_time:.1f}s (attempt {retry_count + 1}/{max_retries})"
                )
                await asyncio.sleep(wait_time)
        
        return None
        
    def get_machine_details_sync(self, system_id: str) -> Optional[Dict[str, Any]]:
        """
        Get full machine details including interfaces and IP addresses (synchronous implementation).
        
        Args:
            system_id: The system ID of the machine
            
        Returns:
            Dictionary containing full machine details if found, None otherwise
        """
        try:
            self.logger.debug(f"Fetching full details for machine with system_id: {system_id}")
            
            # Ensure we have a client connection (synchronous version)
            client = self._ensure_client_sync()
            if not client:
                self.logger.error("Failed to initialize MAAS client")
                return None
            
            # Create a new event loop for this thread
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            try:
                # Create a coroutine for getting machine details
                async def get_machine():
                    return await client.machines.get(system_id=system_id)
                
                # Run the coroutine in the event loop
                self.logger.debug(f"Fetching machine details from MAAS for system_id: {system_id}")
                machine = loop.run_until_complete(get_machine())
                
                if not machine:
                    self.logger.warning(f"No machine found with system_id: {system_id}")
                    return None
                
                # Get IP addresses from the machine's interfaces
                ip_addresses = []
                try:
                    if hasattr(machine, 'interfaces'):
                        for interface in machine.interfaces:
                            if hasattr(interface, 'links'):
                                for link in interface.links:
                                    if hasattr(link, 'ip_address') and link.ip_address:
                                        ip_addresses.append(link.ip_address)
                except Exception as e:
                    self.logger.warning(f"Failed to get IP addresses for machine {system_id}: {e}")
                
                # Convert machine object to dict
                machine_dict = {
                    'system_id': getattr(machine, 'system_id', None),
                    'hostname': getattr(machine, 'hostname', None),
                    'status': getattr(machine, 'status', None),
                    'status_name': getattr(machine, 'status_name', ''),
                    'power_state': getattr(machine, 'power_state', None),
                    'interfaces': [{
                        'name': getattr(iface, 'name', ''),
                        'mac_address': getattr(iface, 'mac_address', ''),
                        'links': [{
                            'ip_address': getattr(link, 'ip_address', ''),
                            'mode': getattr(link, 'mode', ''),
                            'subnet': getattr(link, 'subnet', None),
                        } for link in getattr(iface, 'links', [])]
                    } for iface in getattr(machine, 'interfaces', [])],
                    'ip_addresses': ip_addresses,
                    'fqdn': getattr(machine, 'fqdn', ''),
                    'cpu_count': getattr(machine, 'cpu_count', 0),
                    'memory': getattr(machine, 'memory', 0),
                    'osystem': getattr(machine, 'osystem', ''),
                    'distro_series': getattr(machine, 'distro_series', ''),
                    'hwe_kernel': getattr(machine, 'hwe_kernel', ''),
                    'boot_interface': getattr(machine, 'boot_interface', None),
                    'boot_disk': getattr(machine, 'boot_disk', None),
                    'zone': getattr(machine, 'zone', None),
                    'pool': getattr(machine, 'pool', None),
                    'tag_names': getattr(machine, 'tag_names', []),
                }
                
                self.logger.debug(f"Found machine details: {machine_dict}")
                return machine_dict
                
            except Exception as e:
                self.logger.error(f"Failed to get machine details: {e}")
                if self.debug:
                    self.logger.debug(traceback.format_exc())
                return None
                
            finally:
                # Clean up pending tasks and event loop
                try:
                    pending = asyncio.all_tasks(loop)
                    for task in pending:
                        task.cancel()
                        try:
                            loop.run_until_complete(task)
                        except (asyncio.CancelledError, Exception) as e:
                            self.logger.debug(f"Error cancelling task: {e}")
                            pass
                except Exception as e:
                    self.logger.debug(f"Error cleaning up tasks: {e}")
                finally:
                    loop.close()
                    asyncio.set_event_loop(None)
                    
        except Exception as e:
            self.logger.error(f"Unexpected error in get_machine_details_sync: {e}")
            if self.debug:
                self.logger.debug(traceback.format_exc())
            return None

    def get_machine_by_hostname_sync(self, hostname: str) -> Optional[Dict[str, Any]]:
        """
        Get a machine by its hostname (synchronous implementation).
        
        Args:
            hostname: The hostname of the machine to find
            
        Returns:
            Dictionary containing machine details if found, None otherwise
        """
        try:
            self.logger.debug(f"Looking up machine with hostname: {hostname}")
            
            # Ensure we have a client connection (synchronous version)
            client = self._ensure_client_sync()
            if not client:
                self.logger.error("Failed to initialize MAAS client")
                return None
            
            # Create a new event loop for this thread
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            try:
                # Create a coroutine for listing machines
                async def list_machines():
                    return await client.machines.list()
                
                # Run the coroutine in the event loop
                self.logger.debug("Fetching machines list from MAAS")
                machines = loop.run_until_complete(list_machines())
                self.logger.debug(f"Found {len(machines)} machines in MAAS")
                
            except Exception as e:
                self.logger.error(f"Failed to list machines: {e}")
                if self.debug:
                    self.logger.debug(traceback.format_exc())
                return None
            finally:
                # Clean up pending tasks and event loop
                try:
                    pending = asyncio.all_tasks(loop)
                    for task in pending:
                        task.cancel()
                        try:
                            loop.run_until_complete(task)
                        except (asyncio.CancelledError, Exception) as e:
                            self.logger.debug(f"Error cancelling task: {e}")
                            pass
                except Exception as e:
                    self.logger.debug(f"Error cleaning up tasks: {e}")
                finally:
                    loop.close()
                    asyncio.set_event_loop(None)
            
            if not machines:
                self.logger.warning("No machines returned from MAAS API")
                return None
            
            # Find machine with matching hostname
            for machine in machines:
                machine_hostname = getattr(machine, 'hostname', '')
                if machine_hostname and machine_hostname.lower() == hostname.lower():
                    # Convert machine object to dict
                    machine_dict = {
                        'system_id': machine.system_id,
                        'hostname': machine_hostname,
                        'status': getattr(machine, 'status', None),
                        'status_name': getattr(machine, 'status_name', ''),
                        'power_state': getattr(machine, 'power_state', 'unknown'),
                        'interface_set': getattr(machine, 'interface_set', []),
                        'fqdn': getattr(machine, 'fqdn', ''),
                        'cpu_count': getattr(machine, 'cpu_count', 0),
                        'memory': getattr(machine, 'memory', 0),
                        'osystem': getattr(machine, 'osystem', ''),
                        'distro_series': getattr(machine, 'distro_series', ''),
                        'hwe_kernel': getattr(machine, 'hwe_kernel', '')
                    }
                    self.logger.debug(f"Found machine: {machine_dict}")
                    return machine_dict
            
            self.logger.warning(f"Machine not found with hostname: {hostname}")
            return None
            
        except Exception as e:
            self.logger.error(f"Error in _get_machine_by_hostname_sync for {hostname}: {e}")
            if self.debug:
                self.logger.debug(traceback.format_exc())
            return None
            
    def release_machine_sync(self, system_id: str) -> bool:
        """
        Release a machine (synchronous implementation).
        
        Args:
            system_id: The system ID of the machine to release
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            self.logger.debug(f"Releasing machine {system_id}")
            
            # Ensure we have a client connection (synchronous version)
            client = self._ensure_client_sync()
            if not client:
                self.logger.error("Failed to get MAAS client")
                return False
                
            # Create a new event loop for this thread
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            try:
                # Get the machine
                async def get_machine():
                    return await client.machines.get(system_id)
                    
                machine = loop.run_until_complete(get_machine())
                if not machine:
                    self.logger.error(f"Machine {system_id} not found")
                    return False
                
                # Check if machine is already in Ready state
                current_status = getattr(machine, 'status', None)
                if str(current_status) in ['Ready', '4']:  # 4 is NodeStatus.READY
                    self.logger.info(f"Machine {system_id} is already in Ready state")
                    return True
                
                # Release the machine
                self.logger.info(f"Releasing machine {system_id} (status: {current_status})")
                
                async def release():
                    try:
                        await machine.release()
                    except Exception as e:
                        if "already in the desired state" in str(e):
                            self.logger.info(f"Machine {system_id} is already in the desired state")
                            return True
                        raise
                    
                loop.run_until_complete(release())
                self.logger.info(f"Successfully released machine {system_id}")
                return True
                
            except Exception as e:
                self.logger.error(f"Failed to release machine {system_id}: {e}")
                if self.debug:
                    self.logger.debug(traceback.format_exc())
                return False
                
            finally:
                # Clean up pending tasks and event loop
                try:
                    pending = asyncio.all_tasks(loop)
                    for task in pending:
                        task.cancel()
                        try:
                            loop.run_until_complete(task)
                        except (asyncio.CancelledError, Exception) as e:
                            self.logger.debug(f"Error cancelling task: {e}")
                            pass
                except Exception as e:
                    self.logger.debug(f"Error cleaning up tasks: {e}")
                finally:
                    loop.close()
                    asyncio.set_event_loop(None)
                
        except Exception as e:
            self.logger.error(f"Error in release_machine_sync for {system_id}: {e}")
            if self.debug:
                self.logger.debug(traceback.format_exc())
            return False
    
    def install_machine_sync(self, system_id: str, distro_series: str, hwe_kernel: str = '') -> bool:
        """
        Install a machine (synchronous implementation).
        
        Args:
            system_id: The system ID of the machine to install
            distro_series: The distro series to install (e.g., 'focal')
            hwe_kernel: The HWE kernel to use (optional)
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            self.logger.debug(f"Installing machine {system_id} with {distro_series} (kernel: {hwe_kernel})")
            
            # Ensure we have a client connection (synchronous version)
            client = self._ensure_client_sync()
            if not client:
                self.logger.error("Failed to initialize MAAS client")
                return False
            
            # Create a new event loop for this thread
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            try:
                # Create coroutines for machine operations
                async def get_machine():
                    return await client.machines.get(system_id)
                    
                async def deploy_machine(machine):
                    await machine.deploy(
                        distro_series=distro_series,
                        hwe_kernel=hwe_kernel if hwe_kernel else None,
                        wait=False  # Don't wait for completion
                    )
                
                # Get the machine
                self.logger.debug(f"Fetching machine {system_id} details")
                machine = loop.run_until_complete(get_machine())
                if not machine:
                    self.logger.error(f"Machine {system_id} not found")
                    return False
                
                # Deploy the machine
                self.logger.debug(f"Starting installation of {system_id}")
                loop.run_until_complete(deploy_machine(machine))
                self.logger.info(f"Successfully started installation of {system_id}")
                return True
                
            except Exception as e:
                self.logger.error(f"Failed to install machine {system_id}: {e}")
                if self.debug:
                    self.logger.debug(traceback.format_exc())
                return False
                
            finally:
                # Clean up pending tasks and event loop
                try:
                    pending = asyncio.all_tasks(loop)
                    for task in pending:
                        task.cancel()
                        try:
                            loop.run_until_complete(task)
                        except (asyncio.CancelledError, Exception) as e:
                            self.logger.debug(f"Error cancelling task: {e}")
                            pass
                except Exception as e:
                    self.logger.debug(f"Error cleaning up tasks: {e}")
                finally:
                    loop.close()
                    asyncio.set_event_loop(None)
                
        except Exception as e:
            self.logger.error(f"Error in install_machine_sync for {system_id}: {e}")
            if self.debug:
                self.logger.debug(traceback.format_exc())
            return False
    
    async def _get_machine_by_hostname(self, hostname: str) -> Optional[Dict[str, Any]]:
        """
        Get a machine by its hostname (async implementation).
        
        Args:
            hostname: The hostname of the machine to find
            
        Returns:
            Dictionary containing machine details if found, None otherwise
        """
        try:
            # First try to get the client asynchronously
            try:
                client = await self._ensure_client()
                # Run the synchronous client.machines.list in a thread
                loop = asyncio.get_running_loop()
                machines = await loop.run_in_executor(None, client.machines.list)
            except RuntimeError as e:
                if "no running event loop" in str(e).lower():
                    # If there's no running event loop, fall back to synchronous version
                    self.logger.debug("No running event loop, falling back to sync method")
                    return await asyncio.to_thread(self._get_machine_by_hostname_sync, hostname)
                raise
                
            # Search for machine by hostname
            for machine in machines:
                if getattr(machine, 'hostname', '').lower() == hostname.lower():
                    return {
                        'system_id': machine.system_id,
                        'hostname': getattr(machine, 'hostname', ''),
                        'status': getattr(machine, 'status', None),
                        'status_name': getattr(machine, 'status_name', ''),
                        'power_state': getattr(machine, 'power_state', 'unknown'),
                        'interface_set': getattr(machine, 'interface_set', []),
                        'fqdn': getattr(machine, 'fqdn', ''),
                        'cpu_count': getattr(machine, 'cpu_count', 0),
                        'memory': getattr(machine, 'memory', 0),
                        'osystem': getattr(machine, 'osystem', ''),
                        'distro_series': getattr(machine, 'distro_series', ''),
                        'hwe_kernel': getattr(machine, 'hwe_kernel', '')
                    }
                    
            self.logger.debug(f"No machine found with hostname: {hostname}")
            return None
            
        except Exception as e:
            self.logger.error(f"Error finding machine by hostname {hostname}: {e}")
            if self.debug:
                self.logger.debug(traceback.format_exc())
            # Fall back to sync method on error
            return await asyncio.to_thread(self._get_machine_by_hostname_sync, hostname)
            
    async def get_machine_power_state(self, system_id: str) -> str:
        """
        Get the current power state of a machine.
        
        Args:
            system_id: The system ID of the machine
            
        Returns:
            str: The power state (e.g., 'on', 'off', 'error')
        """
        machine = await self.get_machine(system_id)
        if not machine:
            return "error"
        return machine.get('power_state', 'error')
    
    def _ensure_client_sync(self):
        """Ensure the MAAS client is initialized in a thread-safe manner (synchronous version)."""
        if self._client is None:
            with self._client_lock:
                # Double-checked locking pattern
                if self._client is None:
                    if not MAAS_AVAILABLE:
                        raise ImportError("MAAS client dependencies are not available. Please install python-libmaas.")
                    
                    from maas.client import connect
                    
                    # Create a new event loop for this thread
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    
                    try:
                        self.logger.debug(f"Connecting to MAAS API at {self.url}")
                        # Create a coroutine for the connection
                        async def connect_client():
                            return await connect(self.url, apikey=self.api_key)
                            
                        # Run the coroutine in the event loop
                        self.logger.debug("Running connect coroutine in event loop")
                        self._client = loop.run_until_complete(connect_client())
                        self.logger.debug("Successfully connected to MAAS API")
                        return self._client
                    except Exception as e:
                        self.logger.error(f"Failed to connect to MAAS API: {e}")
                        if self.debug:
                            self.logger.debug(traceback.format_exc())
                        raise
                    finally:
                        # Always clean up the event loop
                        try:
                            pending = asyncio.all_tasks(loop)
                            for task in pending:
                                task.cancel()
                                try:
                                    loop.run_until_complete(task)
                                except asyncio.CancelledError:
                                    pass
                        except Exception as e:
                            self.logger.debug(f"Error cleaning up tasks: {e}")
                        
                        loop.close()
                        asyncio.set_event_loop(None)
        
        return self._client
        
    async def _ensure_client(self):
        """Ensure the MAAS client is initialized in a thread-safe manner (async version)."""
        if self._client is None:
            with self._client_lock:
                # Double-checked locking pattern
                if self._client is None:
                    if not MAAS_AVAILABLE:
                        raise ImportError("MAAS client dependencies are not available. Please install python-libmaas.")
                    
                    from maas.client import connect
                    
                    try:
                        self.logger.debug(f"Connecting to MAAS API at {self.url}")
                        self._client = await connect(
                            self.url,
                            apikey=self.api_key
                        )
                        self.logger.debug("Successfully connected to MAAS API")
                    except Exception as e:
                        self.logger.error(f"Failed to connect to MAAS API: {e}")
                        if self.debug:
                            self.logger.debug(traceback.format_exc())
                        raise
        
        return self._client
    
    async def get_machine_status(self, system_id: str) -> Optional[str]:
        """
        Get the current status of a machine.
        
        Args:
            system_id: The system ID of the machine
            
        Returns:
            Status string if found, None otherwise
        """
        try:
            machine = await self.get_machine(system_id)
            if not machine:
                self.logger.warning(f"Machine {system_id} not found")
                return None
                
            status = machine.get('status_name')
            self.logger.debug(f"Machine {system_id} status: {status}")
            return status
            
        except Exception as e:
            self.logger.error(f"Error getting status for machine {system_id}: {e}")
            if self.debug:
                self.logger.debug(traceback.format_exc())
            return None

    async def get_machine_interfaces(self, system_id: str) -> List[Dict[str, Any]]:
        """
        Get the network interfaces of a machine.
        
        Args:
            system_id: The system ID of the machine
            
        Returns:
            List of interface dictionaries
        """
        try:
            machine = await self.get_machine(system_id)
            if not machine:
                self.logger.warning(f"Machine {system_id} not found when getting interfaces")
                return []
                
            interfaces = machine.get('interface_set', [])
            self.logger.debug(f"Found {len(interfaces)} interfaces for machine {system_id}")
            return interfaces
            
        except Exception as e:
            self.logger.error(f"Error getting interfaces for machine {system_id}: {e}")
            if self.debug:
                self.logger.debug(traceback.format_exc())
            return []

    async def release_machine(self, system_id: str, comment: str = None, force: bool = False) -> bool:
        """
        Release a machine back to MAAS.
        
        Args:
            system_id: The system ID of the machine to release
            comment: Optional comment about the release
            force: Whether to force release even if the machine is in an error state
                
        Returns:
            bool: True if successful, False otherwise
        """
        max_retries = 3
        retry_delay = 5  # seconds
        
        async def _release():
            try:
                client = await self._ensure_client()
                machine = await client.machines.get(system_id=system_id)
                hostname = getattr(machine, 'hostname', f'ID:{system_id}')
                current_status = getattr(machine, 'status_name', '').lower()
                power_state = getattr(machine, 'power_state', 'unknown').lower()
                
                self.logger.info(f"Releasing machine {hostname} (ID: {system_id})")
                self.logger.debug(f"Current status: {current_status}, Power state: {power_state}")
                
                # If machine is already in a released or ready state, no need to release
                if current_status in ['ready', 'new', 'allocated']:
                    self.logger.info(f"Machine {hostname} is already in '{current_status}' state")
                    return True
                
                # Handle machines in a failed or releasing state
                if force and any(status in current_status for status in ['fail', 'error', 'failed', 'releasing']):
                    self.logger.info(f"Machine {hostname} is in {current_status} state, attempting to abort operations...")
                    try:
                        await machine.abort()
                        # Wait for abort to complete
                        await asyncio.sleep(5)
                        # Refresh machine state
                        machine = await client.machines.get(system_id=system_id)
                        current_status = getattr(machine, 'status_name', '').lower()
                        self.logger.info(f"Machine state after abort: {current_status}")
                    except Exception as e:
                        self.logger.warning(f"Could not abort operations: {e}")
                        if not force:
                            return False
                
                # If still in releasing state, wait longer and try to abort
                if current_status == 'releasing':
                    max_wait = 300  # 5 minutes max wait
                    wait_interval = 10  # Check every 10 seconds
                    start_time = time.time()
                    
                    self.logger.warning(f"Machine {hostname} is in 'releasing' state, waiting up to {max_wait} seconds...")
                    
                    while current_status == 'releasing' and (time.time() - start_time) < max_wait:
                        elapsed = int(time.time() - start_time)
                        self.logger.warning(f"Machine {hostname} still releasing after {elapsed} seconds...")
                        
                        # Try to abort if we've been waiting for a while
                        if elapsed > 60 and force:  # After 1 minute, try to abort
                            try:
                                self.logger.warning(f"Attempting to abort stuck release for {hostname}...")
                                await machine.abort()
                                await asyncio.sleep(5)  # Give it some time to process
                            except Exception as e:
                                self.logger.warning(f"Error aborting release: {e}")
                        
                        await asyncio.sleep(wait_interval)
                        machine = await client.machines.get(system_id=system_id)
                        current_status = getattr(machine, 'status_name', '').lower()
                        power_state = getattr(machine, 'power_state', 'unknown').lower()
                        
                        # If we're still releasing after max wait and force is True, try to force release
                        if current_status == 'releasing' and force and (time.time() - start_time) >= max_wait - 30:
                            self.logger.warning(f"Machine {hostname} still stuck in 'releasing' after {max_wait} seconds, attempting force release...")
                            try:
                                await machine.abort()
                                await asyncio.sleep(5)
                                # Try to power off if still on
                                if power_state == 'on':
                                    await machine.power_off()
                                    await asyncio.sleep(5)
                                # Force release
                                await machine.release(comment="Forced release after timeout", force=True)
                                self.logger.warning(f"Force release initiated for {hostname}")
                                return True
                            except Exception as e:
                                self.logger.error(f"Force release failed for {hostname}: {e}")
                                return False
                
                # If machine is powered on, try to power it off first
                if power_state == 'on':
                    self.logger.info(f"Powering off machine {hostname} before release...")
                    try:
                        await machine.power_off()
                        # Wait for power off to complete (up to 30 seconds)
                        for _ in range(10):
                            await asyncio.sleep(3)
                            # Refresh machine state
                            machine = await client.machines.get(system_id=system_id)
                            if getattr(machine, 'power_state', '').lower() != 'on':
                                break
                    except Exception as e:
                        self.logger.warning(f"Could not power off machine: {e}")
                        if not force:
                            return False
                
                # Try to release the machine with retries
                for attempt in range(max_retries):
                    try:
                        release_comment = "Released by infractl" + (f": {comment}" if comment else "")
                        self.logger.info(f"Attempting to release machine (attempt {attempt + 1}/{max_retries})")
                        
                        # Release the machine
                        await machine.release(comment=release_comment, force=force)
                        self.logger.info(f"Successfully released machine {hostname}")
                        return True
                        
                    except Exception as e:
                        if attempt < max_retries - 1:  # Don't sleep on the last attempt
                            self.logger.warning(
                                f"Attempt {attempt + 1}/{max_retries} failed: {e}. "
                                f"Retrying in {retry_delay} seconds..."
                            )
                            await asyncio.sleep(retry_delay)
                        else:
                            self.logger.error(f"Failed to release machine after {max_retries} attempts: {e}")
                            if self.debug:
                                self.logger.debug(traceback.format_exc())
                            return False
                
                return False
                
            except Exception as e:
                self.logger.error(f"Error releasing machine {system_id}: {e}")
                if self.debug:
                    self.logger.debug(traceback.format_exc())
                return False
        
        return await _release()
    
    async def deploy_machine(
        self,
        system_id: str,
        distro_series: str,
        hwe_kernel: str,
        user_data: str = ""
    ) -> bool:
        """Deploy a machine with the specified OS and kernel.
        
        Args:
            system_id: The system ID of the machine to deploy
            distro_series: The Ubuntu distribution series to install (e.g., 'focal', 'jammy')
            hwe_kernel: The HWE kernel to use (e.g., 'ga-20.04', 'hwe-20.04')
            user_data: Optional cloud-init user data as a string or dict
            
        Returns:
            bool: True if deployment was successful, False otherwise
        """
        # Use run_in_executor to handle the synchronous MAAS client calls
        def _deploy():
            try:
                # Ensure we have a client connection
                self._ensure_client()
                
                # Get the machine
                machine = None
                for m in self._client.machines.list():
                    if m.system_id == system_id:
                        machine = m
                        break
                        
                if not machine:
                    self.logger.error(f"Machine {system_id} not found")
                    return False
                
                # Prepare deployment parameters
                deploy_params = {
                    'distro_series': distro_series,
                    'hwe_kernel': hwe_kernel
                }
                
                # Add user_data if provided
                if user_data:
                    user_data_str = user_data
                    if isinstance(user_data, dict):
                        import yaml
                        user_data_str = yaml.dump(user_data, default_flow_style=False)
                    deploy_params['user_data'] = user_data_str
                    
                    # Log a snippet of user_data for debugging (without sensitive info)
                    log_data = user_data_str
                    if len(log_data) > 100:
                        log_data = log_data[:100] + "... [truncated]"
                    self.logger.debug(f"Using user_data: {log_data}")
                
                # Deploy the machine
                machine.deploy(**deploy_params)
                self.logger.info(f"Started deployment of {system_id} with {distro_series} and kernel {hwe_kernel}")
                return True
                
            except Exception as e:
                self.logger.error(f"Error deploying machine {system_id}: {e}")
                if self.debug:
                    self.logger.debug(traceback.format_exc())
                return False
        
        # Run the synchronous code in a thread
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _deploy)

    def power_cycle_machine(self, system_id: str, wait: bool = True, timeout: int = 60) -> bool:
        """
        Power cycle a machine.
        
        Args:
            system_id: The system ID of the machine
            wait: Whether to wait for the power cycle to complete
            timeout: Timeout in seconds to wait for power cycle
                
        Returns:
            bool: True if power cycle was successful, False otherwise
        """
        async def _power_cycle_machine():
            try:
                client = await self._ensure_client()
                machine = await client.machines.get(system_id=system_id)
                if not machine:
                    self.logger.error(f"Machine {system_id} not found")
                    return False
                
                await machine.power_cycle(wait=wait, wait_timeout=timeout)
                self.logger.info(f"Successfully power cycled machine {system_id}")
                return True
                
            except Exception as e:
                self.logger.error(f"Error power cycling machine {system_id}: {e}")
                if self.debug:
                    self.logger.debug(traceback.format_exc())
                return False
        
        return self._run_sync(_power_cycle_machine())
    
    def abort_machine(self, system_id: str) -> bool:
        """
        Abort a machine's current operation.
        
        Args:
            system_id: The system ID of the machine
            
        Returns:
            bool: True if abort was successful, False otherwise
        """
        async def _abort_machine():
            try:
                client = await self._ensure_client()
                machine = await client.machines.get(system_id=system_id)
                if not machine:
                    self.logger.error(f"Machine {system_id} not found")
                    return False
                
                await machine.abort()
                self.logger.info(f"Successfully aborted current operation on machine {system_id}")
                return True
                
            except Exception as e:
                self.logger.error(f"Error aborting machine {system_id}: {e}")
                if self.debug:
                    self.logger.debug(traceback.format_exc())
                return False
        
        return self._run_sync(_abort_machine())
    
    def refresh_power_state(self, system_id: str) -> Optional[str]:
        """
        Refresh the power state of a machine.
        
        Args:
            system_id: The system ID of the machine
            
        Returns:
            The new power state if successful, None otherwise
        """
        async def _refresh_power_state():
            try:
                client = await self._ensure_client()
                machine = await client.machines.get(system_id=system_id)
                if not machine:
                    self.logger.error(f"Machine {system_id} not found")
                    return None
                
                await machine.query_power_state()
                return machine.power_state
                
            except Exception as e:
                self.logger.error(f"Error refreshing power state for machine {system_id}: {e}")
                if self.debug:
                    self.logger.debug(traceback.format_exc())
                return None
        
        return self._run_sync(_refresh_power_state())

def get_maas_client(api_url: str = None, api_key: str = None, debug: bool = False) -> Optional[MAASClient]:
    """
    Get a MAAS client instance using environment variables or provided credentials.
    
    Args:
        api_url: MAAS API URL (optional, will use MAAS_API_URL env var if not provided)
        api_key: MAAS API key (optional, will use MAAS_API_KEY env var if not provided)
        debug: Enable debug logging (default: False)
        
    Returns:
        MAASClient instance or None if initialization fails
    """
    from dotenv import load_dotenv
    
    # Load environment variables from .env file
    load_dotenv()
    
    # Use provided values or fall back to environment variables
    api_url = api_url or os.getenv('MAAS_API_URL')
    api_key = api_key or os.getenv('MAAS_API_KEY')
    
    if not api_url or not api_key:
        logger.error("MAAS API URL and API key must be provided or set in environment variables")
        return None
    
    try:
        logger.debug(f"Initializing MAAS client with URL: {api_url}, debug={debug}")
        
        # Create the client without checking connection immediately
        client = MAASClient(api_url, api_key, debug=debug)
        
        # The actual connection will be established on first use
        logger.debug("MAAS client initialized (lazy connection)")
        return client
        
    except Exception as e:
        logger.error(f"Failed to initialize MAAS client: {e}")
        if debug:
            logger.debug(traceback.format_exc())
    
    return None
