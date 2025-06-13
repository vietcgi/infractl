"""Utility functions and helpers for the infractl application."""
import asyncio
import functools
import json
import logging
import time
from contextlib import asynccontextmanager
from typing import Any, Callable, Dict, List, Optional, Type, TypeVar, cast

from ..config import Config

T = TypeVar('T')

def setup_logging(name: str = None) -> logging.Logger:
    """Set up and return a configured logger instance.
    
    Args:
        name: Name for the logger (usually __name__)
        
    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name or __name__)
    
    # Only configure if not already configured
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter(Config.LOG_FORMAT)
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(Config.LOG_LEVEL)
    
    return logger

def redact_sensitive_data(data: Any) -> Any:
    """Recursively redact sensitive data from dictionaries and lists.
    
    Args:
        data: Input data that might contain sensitive information
        
    Returns:
        Data with sensitive values redacted
    """
    if isinstance(data, dict):
        return {
            k: "[REDACTED]" if any(
                redact_key.lower() in k.lower() 
                for redact_key in Config.REDACT_KEYS
            ) else redact_sensitive_data(v)
            for k, v in data.items()
        }
    elif isinstance(data, (list, tuple)):
        return [redact_sensitive_data(item) for item in data]
    return data

class RetryError(Exception):
    """Custom exception for retry-related errors."""
    pass

def async_retry(
    max_retries: int = None,
    delay: float = None,
    exceptions: tuple[Type[Exception], ...] = (Exception,)
):
    """Decorator for retrying async functions with exponential backoff.
    
    Args:
        max_retries: Maximum number of retry attempts
        delay: Initial delay between retries in seconds
        exceptions: Tuple of exceptions to catch and retry on
        
    Returns:
        Decorated function with retry logic
    """
    if max_retries is None:
        max_retries = Config.MAX_RETRIES
    if delay is None:
        delay = Config.RETRY_DELAY
    
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            last_exception = None
            current_delay = delay
            
            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_retries:
                        wait_time = current_delay * (2 ** attempt)  # Exponential backoff
                        logger = logging.getLogger(__name__)
                        logger.warning(
                            f"Attempt {attempt + 1} failed: {str(e)}. "
                            f"Retrying in {wait_time:.2f}s..."
                        )
                        await asyncio.sleep(wait_time)
            
            raise RetryError(
                f"Failed after {max_retries} attempts. Last error: {str(last_exception)}"
            ) from last_exception
        return wrapper
    return decorator

@asynccontextmanager
async def async_timeout(seconds: float):
    """Async context manager for timeouts.
    
    Args:
        seconds: Timeout in seconds
        
    Yields:
        None
        
    Raises:
        asyncio.TimeoutError: If the operation takes longer than the timeout
    """
    try:
        yield await asyncio.wait_for(asyncio.shield(asyncio.Future()), timeout=seconds)
    except asyncio.TimeoutError:
        raise asyncio.TimeoutError(f"Operation timed out after {seconds} seconds")
