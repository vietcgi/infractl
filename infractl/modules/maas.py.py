"""
MAAS API client module for interacting with MAAS server.
"""
import os
import sys
import logging
import asyncio
import json
import traceback
from typing import Dict, Any, Optional, List, Union, TypeVar, Callable, Coroutine

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
    """Client for interacting with the MAAS API using python-libmaas."""
    
    def __init__(self, api_url: str, api_key: str, debug: bool = False):
        """
        Initialize the MAAS client.
        
        Args:
            api_url: The URL of the MAAS API
            api_key: The API key for authentication
            debug: Enable debug logging if True
        """
        if not MAAS_AVAILABLE:
            raise ImportError("MAAS client dependencies are not available. Please install python-libmaas.")
            
        self.api_url = api_url.rstrip('/')
        self.api_key = api_key
        self._client = None
        self.debug = debug
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
    
    async def get_machine_power_state(self, system_id: str) -> str:
        """
        Get the current power state of a machine.
        
        Args:
            system_id: The system ID of the machine
            
        Returns:
            str: The power state (e.g., 'on', 'off', 'error')
        """
        await self._ensure_client()
        try:
            machine = await asyncio.to_thread(self._client.machines.get, system_id)
            return machine.power_state
        except Exception as e:
            self.logger.error(f"Failed to get power state for machine {system_id}: {e}")
            return "error"
    
    async def _ensure_client(self):
        """Ensure the MAAS client is connected."""
        if self._client is None:
            try:
                # For python-libmaas 0.6.8, we connect directly without using profile registry
                self._client = await maas_connect(
                    self.api_url,
                    apikey=self.api_key,
                )
                self.logger.info(f"Connected to MAAS server at {self.api_url}")
            except Exception as e:
                self.logger.error(f"Failed to connect to MAAS server: {e}")
                if "401" in str(e):
                    raise MAASAuthenticationError("Authentication failed. Check your API key.") from e
                elif "404" in str(e):
                    raise MAASObjectNotFoundError("The requested resource was not found.") from e
                elif any(err in str(e) for err in ["502", "503", "504"]):
                    raise MAASConnectionError("MAAS server is temporarily unavailable.") from e
                else:
                    raise MAASError(f"Failed to connect to MAAS: {e}") from e
        return self._client
    
    @property
    def client(self):
        """Get the MAAS client, connecting if necessary."""
        if not hasattr(self, '_client') or self._client is None:
            self._connect()
        return self._client
        
    def _run_sync(self, coro):
        """Run an async coroutine synchronously."""
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        if loop.is_running():
            # If we're already in an event loop, create a task
            future = asyncio.ensure_future(coro, loop=loop)
            return future.result()
        else:
            # Otherwise, run the loop
            try:
                return loop.run_until_complete(coro)
            finally:
                if loop.is_running():
                    loop.close()
    
    def check_connection(self) -> bool:
        """Check if MAAS API is accessible."""
        try:
            # Create a new event loop for the check
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            try:
                # Try to connect to MAAS
                client = loop.run_until_complete(maas_connect(
                    self.api_url,
                    apikey=self.api_key.strip()
                ))
                
                if client:
                    # If we got a client, try to get the version to verify the connection
                    try:
                        version = loop.run_until_complete(client.version.get())
                        if version:
                            logger.debug(f"Connected to MAAS API version: {version}")
                            return True
                        return False
                    except Exception as e:
                        logger.error(f"Failed to get MAAS version: {str(e)}")
                        return False
                    finally:
                        # Always close the client
                        loop.run_until_complete(client.logout())
                return False
                
            except Exception as e:
                logger.error(f"MAAS connection check failed: {str(e)}")
                return False
                
            finally:
                # Clean up the event loop
                if not loop.is_closed():
                    loop.close()
                    
        except Exception as e:
            logger.error(f"MAAS connection check failed: {str(e)}")
            return False

    async def get_machine_status(self, system_id: str) -> Optional[str]:
        """
        Get the current status of a machine by system ID.
        
        Args:
            system_id: The system ID of the machine
                
        Returns:
            Status string if found, None on error
        """
        machine = await self.get_machine(system_id)
        return machine.get('status_name') if machine else None

    def _connect(self):
        """
        Connect to the MAAS server.
        
        Note: This method is called internally and should not be called directly.
        Use the client property which will call this method if needed.
        """
        if hasattr(self, '_client') and self._client is not None:
            return self._client
            
        try:
            # Parse API key (format: consumer_key:key:secret)
            logger.debug(f"Connecting to MAAS API at {self.api_url}")
            logger.debug(f"API Key (first 10 chars): {self.api_key[:10]}...")
            
            api_key_parts = self.api_key.split(':')
            if len(api_key_parts) != 3:
                logger.error(f"Invalid API key format. Got {len(api_key_parts)} parts, expected 3")
                logger.error(f"API key parts: {api_key_parts}")
                raise ValueError("Invalid API key format. Expected 'consumer_key:key:secret'")
            
            # Create a new event loop for this thread if needed
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            
            logger.debug("Attempting to connect to MAAS API...")
            
            # Connect to MAAS
            try:
                # Create a coroutine for connecting to MAAS
                async def connect_to_maas():
                    return await maas_connect(
                        self.api_url,
                        apikey=self.api_key.strip()  # Strip any whitespace
                    )
                
                # Run the coroutine in the event loop
                self._client = loop.run_until_complete(connect_to_maas())
                logger.info(f"Successfully connected to MAAS API version {self._client.version}")
                return self._client
                
            except Exception as e:
                logger.error(f"Failed to connect to MAAS: {str(e)}")
                if hasattr(self, '_client'):
                    del self._client
                raise
                
        except Exception as e:
            logger.error(f"Error connecting to MAAS: {str(e)}")
            logger.error(f"API URL: {self.api_url}")
            logger.error(f"API Key (first 10 chars): {self.api_key[:10]}...")
            if hasattr(self, '_client'):
                del self._client
            raise
    
    def _run_async(self, coro):
        """Run an async coroutine in a new event loop."""
        # Create a new event loop for this thread
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(coro)
        except Exception as e:
            logger.error(f"Error in async operation: {e}")
            raise
        finally:
            # Clean up the loop
            try:
                # Cancel all tasks
                pending = asyncio.all_tasks(loop=loop)
                for task in pending:
                    task.cancel()
                # Run the event loop again to let tasks handle cancellation
                if pending:
                    loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                # Close the loop
                loop.close()
            except Exception as e:
                logger.warning(f"Error cleaning up event loop: {e}")
            finally:
                asyncio.set_event_loop(None)

    def list_all_machines(self) -> List[Dict[str, Any]]:
        """
        List all machines in MAAS with detailed information.
        
        Returns:
            List of dictionaries containing machine details with the following structure:
            {
                'system_id': str,           # MAAS system ID
                'hostname': str,            # Machine hostname
                'status': str,              # Current status (e.g., 'Ready', 'Deployed')
                'power_state': str,         # Current power state (e.g., 'on', 'off')
                'ip_addresses': List[str],  # List of IP addresses
                'cpu_count': int,           # Number of CPU cores
                'memory': int,              # Memory in MB
                'storage': int,             # Total storage in GB
                'osystem': str,             # Operating system
                'distro_series': str,       # Distribution series
                'hwe_kernel': str,          # HWE kernel version
                'zone': dict,               # Zone information
                'pool': dict,               # Resource pool information
                'owner': str,               # Current owner (if any)
                'tags': List[str],         # List of tags
                'power_type': str,          # Power type (e.g., 'ipmi')
                'power_parameters': dict,   # Power parameters
                'interface_set': List[dict]  # Network interfaces
            }
        """
        async def _list_machines():
            try:
                client = await self._ensure_client()
                self.logger.info("🔍 Listing all machines in MAAS...")
                
                # Get all machines with expanded details
                machines = await client.machines.list()
                self.logger.info(f"✅ Found {len(machines)} machines in MAAS")
                
                # Convert each machine to dict
                result = []
                for machine in machines:
                    try:
                        # Get basic machine info
                        machine_dict = await self._machine_to_dict(machine)
                        
                        # Add additional detailed information
                        machine_dict.update({
                            'zone': {
                                'id': getattr(machine.zone, 'id', None),
                                'name': getattr(machine.zone, 'name', 'default'),
                                'description': getattr(machine.zone, 'description', '')
                            },
                            'pool': {
                                'id': getattr(machine.pool, 'id', None),
                                'name': getattr(machine.pool, 'name', 'default'),
                                'description': getattr(machine.pool, 'description', '')
                            },
                            'owner': getattr(machine, 'owner', ''),
                            'tags': [tag.name for tag in getattr(machine, 'tag_names', [])],
                            'power_type': getattr(machine, 'power_type', 'unknown'),
                            'power_parameters': getattr(machine, 'power_parameters', {}),
                            'interface_set': [
                                {
                                    'name': iface.name,
                                    'type': iface.type,
                                    'mac_address': iface.mac_address,
                                    'vlan': getattr(iface.vlan, 'name', 'untagged') if hasattr(iface, 'vlan') else 'untagged',
                                    'links': [
                                        {
                                            'subnet': getattr(link.subnet, 'cidr', None) if hasattr(link, 'subnet') else None,
                                            'ip_address': link.ip_address,
                                            'mode': link.mode
                                        } for link in getattr(iface, 'links', [])
                                    ]
                                } for iface in getattr(machine, 'interface_set', [])
                            ]
                        })
                        
                        result.append(machine_dict)
                        
                    except Exception as e:
                        self.logger.warning(f"Error processing machine {getattr(machine, 'hostname', 'unknown')}: {e}")
                        if self.debug:
                            self.logger.debug(traceback.format_exc())
                
                return result
                
            except Exception as e:
                error_msg = f"Error listing machines: {e}"
                self.logger.error(error_msg)
                if self.debug:
                    self.logger.debug(traceback.format_exc())
                return []
        
        return self._run_sync(_list_machines())

    def get_machine_by_hostname(self, hostname: str) -> Optional[Dict[str, Any]]:
        """
        Get machine details by hostname.
        
        Args:
            hostname: The hostname to search for
            
        Returns:
            Dict with machine details if found, None if not found or on error
        """
        async def _get_machine_by_hostname():
            try:
                client = await self._ensure_client()
                
                # Log the search with more context
                self.logger.info(f"🔍 Searching MAAS for machine with hostname: {hostname}")
                
                # First try direct lookup by hostname
                try:
                    machines = await client.machines.list(hostnames=[hostname])
                    if machines:
                        self.logger.info(f"✅ Found machine by direct hostname lookup: {hostname}")
                        return await self._machine_to_dict(machines[0])
                except Exception as e:
                    self.logger.warning(f"Direct hostname lookup failed for {hostname}: {e}")
                
                # If direct lookup fails, try listing all machines and searching
                self.logger.info(f"Direct lookup failed, searching all machines for: {hostname}")
                try:
                    all_machines = await client.machines.list()
                    self.logger.info(f"Found {len(all_machines)} total machines in MAAS")
                    
                    # Try exact match first
                    for machine in all_machines:
                        if getattr(machine, 'hostname', '').lower() == hostname.lower():
                            self.logger.info(f"✅ Found exact hostname match: {hostname}")
                            return await self._machine_to_dict(machine)
                    
                    # Try partial match (in case of FQDN vs short name)
                    for machine in all_machines:
                        machine_hostname = getattr(machine, 'hostname', '').lower()
                        if hostname.lower() in machine_hostname or machine_hostname in hostname.lower():
                            self.logger.info(f"✅ Found partial hostname match: {machine_hostname} for {hostname}")
                            return await self._machine_to_dict(machine)
                    
                    # Log some example hostnames for debugging
                    if all_machines and len(all_machines) > 0:
                        example_hostnames = [getattr(m, 'hostname', 'unknown') for m in all_machines[:5]]
                        self.logger.info(f"Example hostnames in MAAS: {', '.join(example_hostnames)}" + 
                                       ("..." if len(all_machines) > 5 else ""))
                
                except Exception as e:
                    self.logger.error(f"Error listing all machines: {e}")
                    if self.debug:
                        self.logger.debug(traceback.format_exc())
                
                self.logger.warning(f"❌ No machine found with hostname: {hostname}")
                return None
                
            except Exception as e:
                error_msg = f"Error getting machine by hostname {hostname}: {e}"
                self.logger.error(error_msg)
                if self.debug:
                    self.logger.debug(traceback.format_exc())
                return None
        
        # Use the helper method to run the async code
        return self._run_sync(_get_machine_by_hostname())
        
    async def _machine_to_dict(self, machine) -> Dict[str, Any]:
        """Convert a MAAS machine object to a dictionary."""
        if machine is None:
            return None
            
        # Get basic attributes with safe defaults
        result = {
            'system_id': getattr(machine, 'system_id', ''),
            'hostname': getattr(machine, 'hostname', ''),
            'status': getattr(machine, 'status_name', 'unknown'),
            'status_name': getattr(machine, 'status_name', 'unknown'),
            'status_code': getattr(machine, 'status', -1),
            'power_state': str(getattr(machine, 'power_state', 'unknown')).lower(),
            'ip_addresses': [],
            'cpu_count': getattr(machine, 'cpu_count', getattr(machine, 'cpu_cores', 0)),
            'memory': getattr(machine, 'memory', 0),
            'architecture': getattr(machine, 'architecture', ''),
            'distro_series': getattr(machine, 'distro_series', ''),
            'osystem': getattr(machine, 'osystem', ''),
            'power_type': getattr(machine, 'power_type', ''),
            'zone': getattr(getattr(machine, 'zone', None), 'name', 'default'),
            'interface_set': [],
            'tag_names': []
        }
        
        # Handle ip_addresses if available
        if hasattr(machine, 'ip_addresses') and machine.ip_addresses:
            result['ip_addresses'] = [ip[0] for ip in machine.ip_addresses if ip and len(ip) > 0]
            
        # Handle interfaces if available
        if hasattr(machine, 'interfaces'):
            result['interface_set'] = []
            for iface in machine.interfaces:
                iface_data = {
                    'name': getattr(iface, 'name', ''),
                    'mac_address': getattr(iface, 'mac_address', ''),
                    'links': []
                }
                
                # Handle links if available
                if hasattr(iface, 'links'):
                    for link in iface.links:
                        link_data = {
                            'ip_address': getattr(link, 'ip_address', None),
                            'mode': getattr(link, 'mode', None)
                        }
                        if hasattr(link, 'subnet') and link.subnet:
                            link_data['subnet'] = getattr(link.subnet, 'cidr', None)
                        iface_data['links'].append(link_data)
                
                result['interface_set'].append(iface_data)
        
        # Handle tags if available
        if hasattr(machine, 'tags'):
            result['tag_names'] = [getattr(tag, 'name', '') for tag in machine.tags]
            
        return result
    
    def get_machine(self, system_id: str, max_retries: int = 3, retry_delay: float = 1.0) -> Optional[Dict[str, Any]]:
        """
        Get machine details by system ID with retry logic for temporary failures.
        
        Args:
            system_id: The system ID of the machine to get
            max_retries: Maximum number of retry attempts
            retry_delay: Delay between retries in seconds
            
        Returns:
            Dict with machine details if found, None if not found or on error
        """
        async def _get_machine():
            last_exception = None
            
            for attempt in range(max_retries):
                try:
                    client = await self._ensure_client()
                    machine = await client.machines.get(system_id=system_id)
                    if not machine:
                        self.logger.warning(f"Machine {system_id} not found (attempt {attempt + 1}/{max_retries})")
                        if attempt < max_retries - 1:
                            await asyncio.sleep(retry_delay)
                            continue
                        return None
                        
                    # Convert machine to dict and return
                    return await self._machine_to_dict(machine)
                    
                except Exception as e:
                    last_exception = e
                    # Don't retry on 404 errors
                    if '404' in str(e):
                        self.logger.warning(f"Machine {system_id} not found (404)")
                        return None
                        
                    self.logger.warning(
                        f"Error getting machine {system_id} (attempt {attempt + 1}/{max_retries}): {e}"
                    )
                    if attempt < max_retries - 1:
                        await asyncio.sleep(retry_delay * (attempt + 1))  # Exponential backoff
            
            # If we get here, all retries failed
            self.logger.error(f"Failed to get machine {system_id} after {max_retries} attempts")
            if self.debug and last_exception:
                self.logger.debug(f"Last exception: {traceback.format_exc()}")
            return None

    
    def get_machine_interfaces(self, system_id: str) -> List[Dict[str, Any]]:
        """
        Get network interfaces for a machine by system ID.
        
        Args:
            system_id: The system ID of the machine
            
        Returns:
                        await asyncio.sleep(retry_delay)
                        continue
                    return None
                    
                # Convert machine to dict and return
                return await self._machine_to_dict(machine)
                
            except Exception as e:
                last_exception = e
                # Don't retry on 404 errors
                if '404' in str(e):
                    self.logger.warning(f"Machine {system_id} not found (404)")
                    return None
                    
                self.logger.warning(
                    f"Error getting machine {system_id} (attempt {attempt + 1}/{max_retries}): {e}"
                )
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay * (attempt + 1))  # Exponential backoff
        
        # If we get here, all retries failed
        self.logger.error(f"Failed to get machine {system_id} after {max_retries} attempts")
        if self.debug and last_exception:
            self.logger.debug(f"Last exception: {traceback.format_exc()}")
        return None

        return machine.get('status_name') if machine else None

    async def get_machine_interfaces(self, system_id: str) -> List[Dict[str, Any]]:
        """
        Get network interfaces for a machine by system ID.
        
        Args:
            system_id: The system ID of the machine
                
        Returns:
            List of interface dictionaries, empty list on error
        """
        machine = await self.get_machine(system_id)
        return machine.get('interface_set', []) if machine else []

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
        
        try:
            client = await self._ensure_client()
            
            # First get the current machine state
            machine = await client.machines.get(system_id=system_id)
            if not machine:
                self.logger.error(f"❌ Machine {system_id} not found")
                return False
            
            hostname = getattr(machine, 'hostname', f'ID:{system_id}')
            self.logger.info(f"🔧 Releasing machine {hostname} (ID: {system_id})")
            
            # Get current status
            current_status = getattr(machine, 'status_name', '').lower()
            power_state = getattr(machine, 'power_state', 'unknown')
            
            self.logger.debug(f"Current status: {current_status}, Power state: {power_state}")
            
            # If machine is already in a released or ready state, no need to release
            if current_status in ['ready', 'new', 'allocated']:
                self.logger.info(f"✅ Machine {hostname} is already in '{current_status}' state")
                return True
            
            # If machine is in a failed state and force is not set, log a warning
            if any(status in current_status for status in ['fail', 'error', 'failed']) and not force:
                self.logger.warning(
                    f"⚠️  Machine {hostname} is in a failed state. "
                    "Use force=True to release it anyway."
                )
                return False
            
            # If machine is powered on, try to power it off first
            if power_state == 'on':
                self.logger.info(f"🔌 Powering off machine {hostname} before release...")
                try:
                    await machine.power_off()
                    # Wait for power off to complete
                    for _ in range(10):  # Wait up to 30 seconds for power off
                        await asyncio.sleep(3)
                        machine = await client.machines.get(system_id=system_id)
                        if not machine or getattr(machine, 'power_state', '') != 'on':
                            break
                except Exception as e:
                    self.logger.warning(f"⚠️  Could not power off machine: {e}")
                    if not force:
                        return False
            
            # Try to release the machine with retries
            for attempt in range(max_retries):
                try:
                    release_comment = "Released by infractl" + (f": {comment}" if comment else "")
                    self.logger.info(f"🔄 Attempting to release machine (attempt {attempt + 1}/{max_retries})")
                    
                    # If force is True, try to abort any ongoing operations first
                    if force:
                        try:
                            await machine.abort()
                            await asyncio.sleep(5)  # Give it some time to abort
                        except Exception as e:
                            self.logger.debug(f"Could not abort operations (may not be needed): {e}")
                    
                    # Release the machine
                    await machine.release(comment=release_comment, erase=force)
                    self.logger.info(f"✅ Successfully released machine {hostname}")
                    return True
                    
                except Exception as e:
                    if attempt == max_retries - 1:  # Last attempt
                        self.logger.error(f"❌ Failed to release machine after {max_retries} attempts: {e}")
                        if self.debug:
                            self.logger.debug(traceback.format_exc())
                        return False
                    
                    # Exponential backoff
                    wait_time = retry_delay * (2 ** attempt)
                    self.logger.warning(
                        f"⚠️  Attempt {attempt + 1} failed: {e}. "
                        f"Retrying in {wait_time} seconds..."
                    )
                    await asyncio.sleep(wait_time)
            
            return False
            
        except Exception as e:
            self.logger.error(f"❌ Error releasing machine {system_id}: {e}")
            if self.debug:
                self.logger.debug(traceback.format_exc())
            return False
    
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
        async def _deploy_machine():
            try:
                client = await self._ensure_client()
                machine = await client.machines.get(system_id=system_id)
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
                await machine.deploy(**deploy_params)
                self.logger.info(f"Started deployment of {system_id} with {distro_series} and kernel {hwe_kernel}")
                return True
                
            except Exception as e:
                self.logger.error(f"Error deploying machine {system_id}: {e}")
                if self.debug:
                    self.logger.debug(traceback.format_exc())
                return False
        
        return self._run_sync(_deploy_machine())

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
