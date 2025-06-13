#!/usr/bin/env python3
"""RKE2 Installer CLI entry point.

This module provides a command-line interface for the RKE2 installer.
It can be used for testing and development purposes.
"""

import argparse
import logging
import sys
from typing import List, Optional

from .core import RKE2Installer
from .models import Node, NodeRole, ClusterConfig
from .deployment import deploy_cluster
from .verification import check_cluster_health


def setup_logging(verbose: bool = False) -> None:
    """Configure logging for the CLI.
    
    Args:
        verbose: Enable verbose logging if True
    """
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        stream=sys.stdout
    )


def parse_args(args: List[str]) -> argparse.Namespace:
    """Parse command line arguments.
    
    Args:
        args: Command line arguments
        
    Returns:
        Parsed arguments
    """
    parser = argparse.ArgumentParser(description='RKE2 Cluster Installer')
    
    # Global options
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Enable verbose output'
    )
    
    # Subcommands
    subparsers = parser.add_subparsers(dest='command', help='Command to run')
    
    # Install command
    install_parser = subparsers.add_parser('install', help='Install RKE2 on nodes')
    install_parser.add_argument(
        '--masters',
        nargs='+',
        required=True,
        help='Master node addresses (user@host)'
    )
    install_parser.add_argument(
        '--workers',
        nargs='*',
        default=[],
        help='Worker node addresses (user@host)'
    )
    install_parser.add_argument(
        '--ssh-key',
        help='Path to SSH private key for authentication'
    )
    install_parser.add_argument(
        '--cluster-name',
        default='rke2-cluster',
        help='Name of the cluster'
    )
    
    # Check command
    check_parser = subparsers.add_parser('check', help='Check cluster health')
    check_parser.add_argument(
        '--master',
        required=True,
        help='Master node address (user@host)'
    )
    check_parser.add_argument(
        '--ssh-key',
        help='Path to SSH private key for authentication'
    )
    
    return parser.parse_args(args)


def main(args: Optional[List[str]] = None) -> int:
    """Main entry point for the CLI.
    
    Args:
        args: Command line arguments (default: None, uses sys.argv[1:])
        
    Returns:
        int: Exit code (0 for success, non-zero for failure)
    """
    if args is None:
        args = sys.argv[1:]
    
    parsed_args = parse_args(args)
    setup_logging(verbose=parsed_args.verbose)
    logger = logging.getLogger(__name__)
    
    try:
        if parsed_args.command == 'install':
            # Parse node addresses
            master_nodes = [
                Node(
                    name=f"master-{i}",
                    ip=addr.split('@')[-1],
                    role=NodeRole.MASTER,
                    user=addr.split('@')[0] if '@' in addr else 'root',
                    ssh_key_path=parsed_args.ssh_key
                )
                for i, addr in enumerate(parsed_args.masters, 1)
            ]
            
            worker_nodes = [
                Node(
                    name=f"worker-{i}",
                    ip=addr.split('@')[-1],
                    role=NodeRole.WORKER,
                    user=addr.split('@')[0] if '@' in addr else 'root',
                    ssh_key_path=parsed_args.ssh_key
                )
                for i, addr in enumerate(parsed_args.workers, 1)
            ]
            
            # Create cluster config
            config = ClusterConfig(
                cluster_name=parsed_args.cluster_name,
                tls_san=[node.ip for node in master_nodes]
            )
            
            # Deploy the cluster
            success = deploy_cluster(
                master_nodes=master_nodes,
                worker_nodes=worker_nodes,
                config=config,
                reset_nodes=True,
                wait_timeout=600
            )
            
            if not success:
                logger.error("Cluster deployment failed")
                return 1
                
            logger.info("Cluster deployed successfully")
            return 0
            
        elif parsed_args.command == 'check':
            # Create a node object for the master
            master_node = Node(
                name='master-1',
                ip=parsed_args.master.split('@')[-1],
                role=NodeRole.MASTER,
                user=parsed_args.master.split('@')[0] if '@' in parsed_args.master else 'root',
                ssh_key_path=parsed_args.ssh_key
            )
            
            # Check cluster health
            health = check_cluster_health([master_node])
            if health.is_healthy:
                logger.info("Cluster is healthy")
                return 0
            else:
                logger.error("Cluster is not healthy")
                for component, status in health.components.items():
                    if not status.healthy:
                        logger.error(f"Component {component} is not healthy: {status.message}")
                return 1
                
        else:
            logger.error("No command specified")
            return 1
            
    except Exception as e:
        logger.exception(f"Error: {e}")
        return 1


if __name__ == '__main__':
    sys.exit(main())
