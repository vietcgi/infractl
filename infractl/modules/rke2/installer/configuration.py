"""RKE2 configuration management.

This module handles all RKE2 configuration generation and management using Jinja2 templates.
The main entry point is the `render_config()` function which generates the configuration
for a node based on its role (bootstrap, server, or agent).

Configuration is defined in templates/config.yaml.j2 and rendered with the following context:
- node: Node object with name and ip attributes
- cluster_token: String used for node authentication
- is_server: Boolean indicating if this is a server node
- is_bootstrap: Boolean indicating if this is the bootstrap node
- bootstrap_ip: String IP of the bootstrap node (if not this node)
"""

import logging
import os
from pathlib import Path
from typing import Dict, Any, Optional, List, Union

from jinja2 import (
    Environment, 
    FileSystemLoader, 
    TemplateNotFound, 
    TemplateSyntaxError, 
    UndefinedError,
    StrictUndefined
)

from ..models import Node

logger = logging.getLogger("rke2.installer.configuration")

class ConfigurationError(Exception):
    """Raised when there is an error generating the configuration."""
    pass

def _validate_node(node: Node) -> None:
    """Validate that a Node object has required attributes.
    
    Args:
        node: Node object to validate
        
    Raises:
        ConfigurationError: If node is invalid
    """
    if not isinstance(node, Node):
        raise ConfigurationError(f"Expected Node object, got {type(node).__name__}")
    
    required_attrs = ['name', 'ip', 'role']
    for attr in required_attrs:
        if not hasattr(node, attr):
            raise ConfigurationError(f"Node is missing required attribute: {attr}")
        if not getattr(node, attr):
            raise ConfigurationError(f"Node {attr} cannot be empty")

def get_template_path() -> str:
    """Get the absolute path to the templates directory."""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates')

def render_config(
    node: Node,
    cluster_token: str,
    is_server: bool = False,
    is_bootstrap: bool = False,
    bootstrap_ip: Optional[str] = None
) -> str:
    """Render the RKE2 configuration using Jinja2 templates.
    
    This function validates all inputs, loads the template, and renders the configuration.
    It handles all template-related errors and provides meaningful error messages.
    
    Args:
        node: The node to generate config for. Must have 'name', 'ip', and 'role' attributes.
        cluster_token: Cluster join token. Must be a non-empty string.
        is_server: Whether this is a server node. Defaults to False.
        is_bootstrap: Whether this is the bootstrap node. Defaults to False.
        bootstrap_ip: IP of the bootstrap node (if not this node). Required if is_bootstrap is False.
        
    Returns:
        str: Rendered YAML configuration
        
    Raises:
        ConfigurationError: If there's an error with the configuration or template
        FileNotFoundError: If the template file is not found
        
    Example:
        ```python
        node = Node(name='node1', ip='10.0.0.1', role='master')
        config = render_config(
            node=node,
            cluster_token='my-cluster-token',
            is_server=True,
            is_bootstrap=True
        )
        ```
    """
    try:
        # Validate inputs
        _validate_node(node)
        
        if not cluster_token or not isinstance(cluster_token, str):
            raise ConfigurationError("cluster_token must be a non-empty string")
            
        if is_server and not is_bootstrap and not bootstrap_ip:
            raise ConfigurationError("bootstrap_ip is required for non-bootstrap server nodes")
        
        # Set up Jinja2 environment with strict undefined handling
        env = Environment(
            loader=FileSystemLoader(get_template_path()),
            trim_blocks=True,
            lstrip_blocks=True,
            undefined=StrictUndefined  # Raise error for undefined variables
        )
        
        # Load and render the template
        try:
            template = env.get_template('config.yaml.j2')
            return template.render(
                node=node,
                cluster_token=cluster_token,
                is_server=is_server,
                is_bootstrap=is_bootstrap,
                bootstrap_ip=bootstrap_ip
            )
        except TemplateNotFound as e:
            raise FileNotFoundError(f"Configuration template not found: {e}") from e
        except TemplateSyntaxError as e:
            raise ConfigurationError(f"Template syntax error: {e}") from e
        except UndefinedError as e:
            raise ConfigurationError(f"Missing required template variable: {e}") from e
            
    except Exception as e:
        if not isinstance(e, ConfigurationError):
            raise ConfigurationError(f"Failed to generate configuration: {str(e)}") from e
        raise

def generate_node_config(node: Node, cluster_token: str, master_nodes: list = None, bootstrap_ip: str = None) -> Dict[str, Any]:
    """Generate RKE2 node configuration.
    
    Args:
        node: Node to generate config for
        cluster_token: Cluster join token
        master_nodes: List of master nodes
        bootstrap_ip: IP of the bootstrap node (None for bootstrap node)
        
    Returns:
        dict: RKE2 node configuration
    """
    # Start with base config
    config = {
        'token': cluster_token,
        'node-ip': node.ip,
        'node-name': node.name,
        'node-external-ip': node.ip,
        'disable': [
            'rke2-canal',
            'rke2-coredns',
            'rke2-ingress-nginx',
            'rke2-metrics-server',
            'rke2-snapshot-controller',
            'rke2-snapshot-controller-crd',
            'rke2-snapshot-validation-webhook'
        ],
        'write-kubeconfig-mode': '0644',
        'write-kubeconfig': '/etc/rancher/rke2/rke2.yaml'
    }
    
    # Add TLS SANs for API server on master nodes
    if node.role == 'master':
        config['tls-san'] = [
            node.ip,  # Node's IP address
            '127.0.0.1',  # IPv4 localhost
            'localhost',  # Local hostname
            '::1',  # IPv6 localhost
            'kubernetes',  # Kubernetes service name
            'kubernetes.default',  # Kubernetes default service
            'kubernetes.default.svc',  # Kubernetes service domain
            'kubernetes.default.svc.cluster.local'  # Full service domain
        ]
    
    # Handle master node configuration
    if node.role == 'master':
        # Only set server URL for non-bootstrap master nodes
        if bootstrap_ip and bootstrap_ip != node.ip:
            config['server'] = f'https://{bootstrap_ip}:9345'
        
        # Get all master node IPs for tls-san
        master_ips = []
        if master_nodes:
            for n in master_nodes:
                if hasattr(n, 'ip') and n.ip:
                    ip = n.ip.split('\n')[0].strip()
                    if ip not in master_ips:
                        master_ips.append(ip)
        
        # If no master IPs found, use the current node's IP
        if not master_ips and hasattr(node, 'ip') and node.ip:
            ip = node.ip.split('\n')[0].strip()
            if ip not in master_ips:
                master_ips.append(ip)
        
        # Add TLS SANs for API server
        if 'tls-san' not in config:
            config['tls-san'] = []
            
        # Add master IPs to TLS SANs if not already present
        for ip in master_ips:
            if ip and ip not in config['tls-san']:
                config['tls-san'].append(ip)
        
        # Add essential Kubernetes service DNS names and localhost addresses
        local_sans = [
            '127.0.0.1',
            'localhost',
            '::1',
            'kubernetes',
            'kubernetes.default',
            'kubernetes.default.svc',
            'kubernetes.default.svc.cluster.local'
        ]
        
        for san in local_sans:
            if san not in config['tls-san']:
                config['tls-san'].append(san)
        
        # Add kube-apiserver and controller manager args
        config.update({
            'kube-apiserver-arg': [
                'default-not-ready-toleration-seconds=30',
                'default-unreachable-toleration-seconds=30',
                'feature-gates=RotateKubeletServerCertificate=true',
                'service-node-port-range=30000-32767'
            ],
            'kube-controller-manager-arg': [
                'node-monitor-grace-period=20s',
                'node-monitor-period=5s',
                'feature-gates=RotateKubeletServerCertificate=true',
                'node-cidr-mask-size=24'
            ]
        })
        
        # Server URL is already set above for additional masters
    else:
        # Agent configuration
        if bootstrap_ip:
            config['server'] = f'https://{bootstrap_ip}:9345'
    
    # Common kubelet and kube-proxy arguments for all nodes
    kubelet_args = [
        f'node-ip={node.ip}',
        f'node-labels=node.kubernetes.io/instance-type=rke2',
        'cloud-provider=external',
        'cgroup-driver=systemd',
        'volume-plugin-dir=/var/lib/kubelet/volumeplugins',
        'read-only-port=0',
        'feature-gates=RotateKubeletServerCertificate=true',
        'serialize-image-pulls=false',
        'fail-swap-on=false'
    ]
    
    # Add node taints for etcd nodes
    if node.role == 'etcd' or (hasattr(node, 'role') and node.role == 'master' and getattr(node, 'etcd', True)):
        kubelet_args.append('register-with-taints=node-role.kubernetes.io/etcd:NoSchedule')
    
    config['kubelet-arg'] = kubelet_args
    
    config['kube-proxy-arg'] = [
        'metrics-bind-address=0.0.0.0:10249'
    ]
    
    # For agent nodes, ensure we have a server URL and token
    if node.role != 'master' and bootstrap_ip:
        config['server'] = f'https://{bootstrap_ip}:9345'
    
    # Add node labels if specified
    if hasattr(node, 'labels') and node.labels:
        config['node-label'] = [f"{k}={v}" for k, v in node.labels.items()]
    
    # Add node taints if specified
    if hasattr(node, 'taints') and node.taints:
        config['node-taint'] = [f"{k}={v}:NoSchedule" for k, v in node.taints.items()]
    
    # Add kubelet args if specified
    if hasattr(node, 'kubelet_args') and node.kubelet_args:
        if 'kubelet-arg' not in config:
            config['kubelet-arg'] = []
        config['kubelet-arg'].extend([f"{k}={v}" for k, v in node.kubelet_args.items()])
    
    return config

def write_node_config(installer, node: Node, config: Dict[str, Any]) -> None:
    """Write RKE2 configuration to a node in an idempotent way.
    
    Args:
        installer: RKE2Installer instance
        node: Node to write config to
        config: Configuration to write
        
    Raises:
        RuntimeError: If writing config fails
    """
    import tempfile
    import yaml
    import hashlib
    import json
    
    def safe_clean_config(obj):
        """Safely clean config objects for YAML serialization."""
        if obj is None:
            return None
        if isinstance(obj, (str, int, float, bool)):
            return str(obj)
        if isinstance(obj, dict):
            return {str(k): safe_clean_config(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [safe_clean_config(x) for x in obj]
        if hasattr(obj, '__dict__'):
            return safe_clean_config(obj.__dict__)
        return str(obj)
    
    try:
        logger.info(f"📝 Writing RKE2 config to {node.name}...")
        
        # Clean the config to ensure it's YAML serializable
        cleaned_config = safe_clean_config(config)
        
        # Create a safe version of the config for logging (without sensitive data)
        safe_config = cleaned_config.copy() if isinstance(cleaned_config, dict) else {}
        if 'token' in safe_config:
            safe_config['token'] = '***REDACTED***'
        
        logger.debug(f"Configuration to write: {json.dumps(safe_config, indent=2)}")
        
        # Generate YAML content with safe settings
        import io
        
        # Use a string buffer to capture YAML output
        yaml_buffer = io.StringIO()
        
        # Dump YAML with safe settings
        yaml.safe_dump(
            cleaned_config,
            yaml_buffer,
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
            width=float('inf'),
            default_style=None,
            explicit_start=True
        )
        
        # Get the YAML content and ensure consistent line endings
        config_yaml = yaml_buffer.getvalue().replace('\r\n', '\n').replace('\r', '\n')
        config_yaml = '\n'.join(line.rstrip() for line in config_yaml.splitlines()) + '\n'
        
        # Create a temporary file with the config
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', delete=False) as f:
            f.write(config_yaml)
            local_temp = f.name
        
        try:
            remote_temp_path = f'/tmp/rke2-config-{node.name}.yaml.tmp'
            remote_final_path = '/etc/rancher/rke2/config.yaml'
            
            # Check if the remote file exists and has the same content
            try:
                # Get the checksum of the new config
                new_checksum = hashlib.md5(config_yaml.encode('utf-8')).hexdigest()
                
                # Get checksum of remote file if it exists
                remote_checksum = installer._ssh_exec(
                    node,
                    f'sudo test -f {remote_final_path} && sudo md5sum {remote_final_path} 2>/dev/null | cut -d" " -f1 || echo "no-such-file"',
                    check=False
                ).strip()
                
                if remote_checksum == new_checksum:
                    logger.info(f'✅ RKE2 config is already up to date on {node.name}')
                    return
                    
            except Exception as e:
                logger.debug(f"Could not verify remote checksum: {str(e)}")
            
            # Upload the new config to a temporary location
            logger.debug(f"Uploading config to {node.name}:{remote_temp_path}")
            installer._sftp_put(node, local_temp, remote_temp_path)
            
            # Ensure the target directory exists with correct permissions
            try:
                logger.debug(f"Ensuring directory exists: /etc/rancher/rke2 on {node.name}")
                installer._ssh_exec(
                    node,
                    'sudo mkdir -p /etc/rancher/rke2 && ' \
                    'sudo chmod 755 /etc/rancher /etc/rancher/rke2 && ' \
                    'sudo chown root:root /etc/rancher /etc/rancher/rke2',
                    check=True
                )
                
                # Verify directory permissions
                dir_check = installer._ssh_exec(
                    node,
                    'stat -c "%a %U:%G" /etc/rancher/rke2',
                    check=False
                ).strip()
                logger.debug(f"Directory permissions: {dir_check}")
                
            except Exception as e:
                logger.error(f"Failed to create/setup directory /etc/rancher/rke2: {str(e)}")
                raise
            
            # Move to final location with proper permissions atomically
            try:
                logger.debug(f"Moving config to final location: {remote_final_path}")
                
                # First, ensure the parent directory exists with correct permissions
                parent_dir = '/etc/rancher/rke2'
                installer._ssh_exec(
                    node,
                    f'sudo mkdir -p {parent_dir} && ' \
                    f'sudo chmod 755 {parent_dir} && ' \
                    f'sudo chown root:root {parent_dir}',
                    check=True
                )
                
                # Debug: List directory contents
                installer._ssh_exec(
                    node,
                    f'sudo ls -la {parent_dir}',
                    check=False
                )
                
                # Move the file using a multi-step process with error checking
                cmds = [
                    # Ensure temp file exists and has content
                    f'test -f {remote_temp_path} && echo "Temp file exists" || (echo "Temp file missing"; exit 1)',
                    # Move the file with atomic rename
                    f'sudo mv -f {remote_temp_path} {remote_final_path}.new',
                    # Set permissions on the new file
                    f'sudo chmod 600 {remote_final_path}.new',
                    f'sudo chown root:root {remote_final_path}.new',
                    # Atomically rename to final location
                    f'sudo mv -f {remote_final_path}.new {remote_final_path}'
                ]
                
                # Execute commands one by one with error checking
                for cmd in cmds:
                    logger.debug(f"Executing: {cmd}")
                    output = installer._ssh_exec(node, cmd, check=True)
                    logger.debug(f"Output: {output}")
                    
            except Exception as e:
                # Provide detailed error information
                logger.error(f"❌ Failed to move config file: {str(e)}")
                
                # Gather debug information
                try:
                    # Check temp file
                    temp_info = installer._ssh_exec(
                        node,
                        f'ls -la {remote_temp_path} 2>/dev/null || echo "Temp file not found"',
                        check=False
                    ).strip()
                    logger.debug(f"Temp file info: {temp_info}")
                    
                    # Check destination directory
                    dir_info = installer._ssh_exec(
                        node,
                        'ls -la /etc/rancher/rke2/ 2>/dev/null || echo "Directory not found"',
                        check=False
                    ).strip()
                    logger.debug(f"Destination directory info: {dir_info}")
                    
                    # Check disk space
                    disk_info = installer._ssh_exec(
                        node,
                        'df -h /etc/rancher',
                        check=False
                    ).strip()
                    logger.debug(f"Disk space info: {disk_info}")
                    
                except Exception as debug_e:
                    logger.error(f"Failed to gather debug info: {debug_e}")
                
                raise
            
            # Verify the file was written
            installer._ssh_exec(node, f"sudo ls -la {remote_final_path}")
            logger.info(f"✅ Successfully updated RKE2 config on {node.name}")
            
        except Exception as e:
            logger.error(f"❌ Failed to write config to {node.name}: {e}", exc_info=True)
            # Try to get more info about the remote file
            try:
                installer._ssh_exec(node, f"sudo ls -la $(dirname {remote_final_path})/")
                installer._ssh_exec(node, f"sudo cat {remote_final_path} 2>&1 || true")
            except Exception as debug_e:
                logger.error(f"Debug info failed: {debug_e}")
            raise
            
        finally:
            # Clean up local temp file
            try:
                if os.path.exists(local_temp):
                    os.unlink(local_temp)
                    logger.debug(f"Cleaned up local temp file: {local_temp}")
            except Exception as e:
                logger.warning(f"Failed to clean up local temp file {local_temp}: {e}")
                
    except Exception as e:
        error_msg = f'Failed to write RKE2 config to {node.name}: {str(e)}'
        logger.error(error_msg, exc_info=True)
        raise RuntimeError(error_msg) from e
