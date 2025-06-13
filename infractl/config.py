"""Configuration management for the infractl application."""
import os
from typing import Dict, Any, Optional
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file if it exists
load_dotenv()

class Config:
    """Application configuration with sensible defaults."""
    
    # MAAS API Configuration
    MAAS_URL: str = os.getenv("MAAS_URL", os.getenv("MAAS_API_URL", ""))
    MAAS_API_KEY: str = os.getenv("MAAS_API_KEY", "")
    
    # Timeouts (in seconds)
    API_TIMEOUT: int = int(os.getenv("API_TIMEOUT", "30"))
    SSH_TIMEOUT: int = int(os.getenv("SSH_TIMEOUT", "10"))
    DEPLOYMENT_TIMEOUT: int = int(os.getenv("DEPLOYMENT_TIMEOUT", "900"))  # 15 minutes
    
    # Retry configuration
    MAX_RETRIES: int = int(os.getenv("MAX_RETRIES", "3"))
    RETRY_DELAY: float = float(os.getenv("RETRY_DELAY", "1.0"))
    
    # Logging
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()
    LOG_FORMAT: str = os.getenv(
        "LOG_FORMAT", 
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    
    # Security
    REDACT_KEYS: tuple = ("api_key", "password", "secret", "token")
    
    @classmethod
    def validate(cls) -> None:
        """Validate required configuration."""
        required = {
            "MAAS_URL": cls.MAAS_URL,
            "MAAS_API_KEY": cls.MAAS_API_KEY
        }
        missing = [k for k, v in required.items() if not v]
        if missing:
            raise ValueError(f"Missing required configuration: {', '.join(missing)}")

# Don't validate on import to allow for dynamic configuration
# Call Config.validate() explicitly when needed
