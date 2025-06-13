"""RKE2 configuration management utility.

This module provides functions to create, validate, and manage RKE2 configuration files.
"""
import os
import sys
import logging
from pathlib import Path
from typing import Optional, Union, Dict, Any

import yaml
from .config import InstallerConfig, DEFAULT_CONFIG_PATHS

logger = logging.getLogger("rke2.configure")

def create_config_file(
    output_path: Optional[Union[str, Path]] = None,
    overwrite: bool = False,
    interactive: bool = False
) -> Path:
    """Create a new RKE2 configuration file with default values.
    
    Args:
        output_path: Path where to save the configuration file.
                   If None, uses the first writable default location.
        overwrite: If True, overwrite existing file.
        interactive: If True, prompt before overwriting.
        
    Returns:
        Path to the created configuration file.
        
    Raises:
        FileExistsError: If the file exists and overwrite is False.
        PermissionError: If unable to write to the target directory.
    """
    # Determine output path
    if output_path is None:
        # Find the first writable default location
        for path in DEFAULT_CONFIG_PATHS:
            path = path.expanduser().absolute()
            if not path.exists():
                try:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.touch(exist_ok=False)
                    path.unlink()  # Remove the empty file we just created
                    output_path = path
                    break
                except (OSError, PermissionError):
                    continue
        else:
            # If no writable default location, use current directory
            output_path = Path("rke2-config.yaml").absolute()
    else:
        output_path = Path(output_path).expanduser().absolute()
    
    # Check if file exists
    if output_path.exists() and not overwrite:
        if interactive:
            response = input(f"File {output_path} already exists. Overwrite? [y/N] ")
            if not response.lower().startswith('y'):
                print("Operation cancelled.")
                sys.exit(0)
        else:
            raise FileExistsError(f"File already exists: {output_path}")
    
    # Create default config
    config = InstallerConfig()
    
    # Ensure parent directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Save to file
    config.save(output_path)
    logger.info(f"Created configuration file: {output_path}")
    
    # Set appropriate permissions
    try:
        output_path.chmod(0o600)  # Read/write for owner only
    except OSError as e:
        logger.warning(f"Could not set permissions on {output_path}: {e}")
    
    return output_path

def validate_config_file(config_path: Union[str, Path]) -> Dict[str, Any]:
    """Validate a configuration file.
    
    Args:
        config_path: Path to the configuration file.
        
    Returns:
        Dict containing validation results and any errors.
    """
    config_path = Path(config_path).expanduser().absolute()
    result = {
        'valid': False,
        'path': str(config_path),
        'exists': config_path.exists(),
        'errors': [],
        'warnings': []
    }
    
    if not result['exists']:
        result['errors'].append(f"File does not exist: {config_path}")
        return result
    
    try:
        # Try to load the config
        config = InstallerConfig.load(config_path)
        result['valid'] = True
        
        # Check for sensitive values
        if config.ssh.key_path and not os.path.exists(os.path.expanduser(config.ssh.key_path)):
            result['warnings'].append(f"SSH key not found: {config.ssh.key_path}")
        
        # Check file permissions
        if config_path.stat().st_mode & 0o077 != 0:
            result['warnings'].append(
                f"Configuration file has insecure permissions. "
                f"Recommended: chmod 600 {config_path}"
            )
        
        result['config'] = config.dict()
        
    except Exception as e:
        result['errors'].append(f"Invalid configuration: {str(e)}")
    
    return result

def show_config() -> None:
    """Display the current configuration and its source."""
    config = InstallerConfig.load()
    
    print("\nRKE2 Configuration:")
    print("=" * 60)
    
    # Show where the config was loaded from
    loaded_from = "default values"
    for path in DEFAULT_CONFIG_PATHS:
        path = path.expanduser().absolute()
        if path.exists():
            loaded_from = str(path)
            break
    
    print(f"Loaded from: {loaded_from}")
    print("-" * 60)
    
    # Print the configuration
    print(yaml.dump(config.dict(), default_flow_style=False, sort_keys=False))
    
    # Show environment variables that would override the config
    print("\nEnvironment variables that would override this config:")
    print("-" * 60)
    print("RKE2_SSH_USER=username")
    print("RKE2_SSH_KEY_PATH=~/.ssh/id_rsa")
    print("RKE2_SSH_PORT=22")
    print("RKE2_LOG_LEVEL=INFO")
    print("RKE2_CLUSTER_TOKEN=your-token-here")
    print("\nNote: Use double underscores for nested settings, e.g., RKE2_SSH__PORT=2222")

def main():
    """Command-line interface for configuration management."""
    import argparse
    
    parser = argparse.ArgumentParser(description="RKE2 Configuration Manager")
    subparsers = parser.add_subparsers(dest='command', help='Command to run')
    
    # Create command
    create_parser = subparsers.add_parser('create', help='Create a new configuration file')
    create_parser.add_argument(
        '-o', '--output',
        help='Output file path (default: auto-detect)'
    )
    create_parser.add_argument(
        '-f', '--force',
        action='store_true',
        help='Overwrite existing file without prompting'
    )
    
    # Validate command
    validate_parser = subparsers.add_parser('validate', help='Validate a configuration file')
    validate_parser.add_argument(
        'config_file',
        nargs='?',
        help='Configuration file to validate (default: auto-detect)'
    )
    
    # Show command
    subparsers.add_parser('show', help='Show the current configuration')
    
    args = parser.parse_args()
    
    # Set up basic logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(levelname)s: %(message)s'
    )
    
    try:
        if args.command == 'create':
            config_path = create_config_file(
                output_path=args.output,
                overwrite=args.force,
                interactive=not args.force
            )
            print(f"Created configuration file: {config_path}")
            
        elif args.command == 'validate':
            config_path = args.config_file
            if not config_path:
                # Try to find an existing config file
                for path in DEFAULT_CONFIG_PATHS:
                    path = path.expanduser().absolute()
                    if path.exists():
                        config_path = path
                        break
                else:
                    print("No configuration file found.")
                    return 1
            
            result = validate_config_file(config_path)
            if result['valid']:
                print(f"✅ Configuration is valid: {result['path']}")
                if result.get('warnings'):
                    print("\nWarnings:")
                    for warning in result['warnings']:
                        print(f"  ⚠️  {warning}")
            else:
                print(f"❌ Configuration is invalid: {result['path']}")
                if result.get('errors'):
                    print("\nErrors:")
                    for error in result['errors']:
                        print(f"  ❌ {error}")
        
        elif args.command == 'show':
            show_config()
        
        else:
            parser.print_help()
        
        return 0
        
    except Exception as e:
        logger.error(f"Error: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())
