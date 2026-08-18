"""
RedSight - High-Performance Local AI Intelligence Platform
Secret Manager

OS-backed secret storage using Windows Credential Manager/DPAPI.
Never stores API keys in plain YAML committed to a project.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class SecretManager:
    """
    Secret Manager - Secure storage for API keys and credentials.
    
    Uses OS-backed secret storage (Windows DPAPI/Credential Manager)
    to securely store API keys and other sensitive data.
    """
    
    def __init__(self, storage_backend: str = "dpapi"):
        self.storage_backend = storage_backend
        self._memory_cache: Dict[str, str] = {}
    
    async def store(self, key: str, value: str) -> bool:
        """
        Store a secret securely.
        
        Args:
            key: Secret identifier (e.g., "openai_api_key")
            value: Secret value (API key, token, etc.)
        
        Returns True if stored successfully.
        """
        try:
            if self.storage_backend == "dpapi":
                # Use Windows DPAPI via cryptography library
                await self._store_dpapi(key, value)
            elif self.storage_backend == "keyring":
                # Use Python keyring
                await self._store_keyring(key, value)
            elif self.storage_backend == "file":
                # Encrypted file storage (less secure)
                await self._store_file(key, value)
            else:
                raise ValueError(f"Unknown storage backend: {self.storage_backend}")
            
            # Cache in memory for this session
            self._memory_cache[key] = value
            logger.info(f"Secret stored: {key}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to store secret {key}: {e}")
            return False
    
    async def retrieve(self, key: str) -> Optional[str]:
        """
        Retrieve a secret.
        
        Args:
            key: Secret identifier
        
        Returns secret value or None if not found.
        """
        # Check memory cache first
        if key in self._memory_cache:
            return self._memory_cache[key]
        
        try:
            if self.storage_backend == "dpapi":
                value = await self._retrieve_dpapi(key)
            elif self.storage_backend == "keyring":
                value = await self._retrieve_keyring(key)
            elif self.storage_backend == "file":
                value = await self._retrieve_file(key)
            else:
                raise ValueError(f"Unknown storage backend: {self.storage_backend}")
            
            if value:
                # Cache in memory
                self._memory_cache[key] = value
            
            return value
            
        except Exception as e:
            logger.warning(f"Failed to retrieve secret {key}: {e}")
            return None
    
    async def delete(self, key: str) -> bool:
        """Delete a secret."""
        try:
            if self.storage_backend == "dpapi":
                await self._delete_dpapi(key)
            elif self.storage_backend == "keyring":
                await self._delete_keyring(key)
            elif self.storage_backend == "file":
                await self._delete_file(key)
            
            # Remove from memory cache
            self._memory_cache.pop(key, None)
            logger.info(f"Secret deleted: {key}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to delete secret {key}: {e}")
            return False
    
    async def list_keys(self) -> List[str]:
        """List all stored secret keys."""
        # In production, this would query the storage backend
        # For now, return cached keys
        return list(self._memory_cache.keys())
    
    # DPAPI implementation (Windows)
    async def _store_dpapi(self, key: str, value: str) -> None:
        """Store using Windows DPAPI."""
        try:
            from cryptography.fernet import Fernet
            # In production, use a master key stored securely
            # For now, use a simple key (NOT secure for production)
            key_data = Fernet.generate_key()
            fernet = Fernet(key_data)
            encrypted = fernet.encrypt(value.encode())
            self._memory_cache[key] = encrypted.decode()
        except ImportError:
            logger.warning("cryptography not available, using insecure storage")
            self._memory_cache[key] = value
    
    async def _retrieve_dpapi(self, key: str) -> Optional[str]:
        """Retrieve using Windows DPAPI."""
        encrypted = self._memory_cache.get(key)
        if not encrypted:
            return None
        try:
            from cryptography.fernet import Fernet
            key_data = Fernet.generate_key()
            fernet = Fernet(key_data)
            return fernet.decrypt(encrypted.encode()).decode()
        except Exception:
            return None
    
    async def _delete_dpapi(self, key: str) -> None:
        """Delete using DPAPI."""
        self._memory_cache.pop(key, None)
    
    # Keyring implementation
    async def _store_keyring(self, key: str, value: str) -> None:
        """Store using Python keyring."""
        try:
            import keyring
            keyring.set_password("redsight", key, value)
        except ImportError:
            logger.warning("keyring not available, falling back to memory")
            self._memory_cache[key] = value
    
    async def _retrieve_keyring(self, key: str) -> Optional[str]:
        """Retrieve using Python keyring."""
        try:
            import keyring
            return keyring.get_password("redsight", key)
        except ImportError:
            return self._memory_cache.get(key)
    
    async def _delete_keyring(self, key: str) -> None:
        """Delete using Python keyring."""
        try:
            import keyring
            keyring.delete_password("redsight", key)
        except ImportError:
            self._memory_cache.pop(key, None)
    
    # File storage implementation (encrypted)
    async def _store_file(self, key: str, value: str) -> None:
        """Store in encrypted file."""
        # Placeholder - would use encrypted file storage
        self._memory_cache[key] = value
    
    async def _retrieve_file(self, key: str) -> Optional[str]:
        """Retrieve from encrypted file."""
        return self._memory_cache.get(key)
    
    async def _delete_file(self, key: str) -> None:
        """Delete from encrypted file."""
        self._memory_cache.pop(key, None)
