"""Configuration management for the Telegram Download Chat GUI."""
import base64
import logging
import yaml
from pathlib import Path
from typing import Dict, Any, Optional, Union, TypeVar, Type, cast
from telegram_download_chat.paths import get_app_dir, ensure_app_dirs


# Type variable for YAML representers
T = TypeVar('T')


def get_default_config_path() -> Path:
    """Get the path to the default config file.
    
    Returns:
        Path: Path to the config file
    """
    return get_app_dir() / 'config.yml'


class ConfigManager:
    """Manages application configuration."""
    
    def __init__(self, config_path: Optional[Path] = None):
        """Initialize the config manager.
        
        Args:
            config_path: Optional path to the config file. If not provided, the default path will be used.
        """
        ensure_app_dirs()
        self.config_path = config_path or get_default_config_path()
        self.config: Dict[str, Any] = {'settings': {}}
        
    def _decode_binary(self, data: Any) -> Any:
        """Recursively decode binary data in the config."""
        if isinstance(data, dict):
            return {k: self._decode_binary(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [self._decode_binary(item) for item in data]
        elif isinstance(data, str) and data.startswith('!!binary '):
            try:
                return base64.b64decode(data[9:].encode('utf-8'))
            except Exception as e:
                logging.warning(f"Failed to decode binary data: {e}")
                return data
        return data

    def load(self) -> None:
        """Load configuration from file."""
        if self.config_path.exists():
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    self.config = yaml.safe_load(f) or {'settings': {}}
                    # Decode any binary data
                    self.config = self._decode_binary(self.config)
            except Exception as e:
                logging.error(f"Error loading config from {self.config_path}: {e}")
                self.config = {'settings': {}}
    
    def _encode_binary(self, data: Any) -> Any:
        """Recursively encode binary data in the config."""
        if isinstance(data, dict):
            return {k: self._encode_binary(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [self._encode_binary(item) for item in data]
        elif isinstance(data, bytes):
            return f"!!binary {base64.b64encode(data).decode('utf-8')}"
        return data

    def save(self) -> None:
        """Save configuration to file."""
        try:
            # Ensure the directory exists
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Create a sanitized copy of the config
            config_to_save = {}
            for key, value in self.config.items():
                if isinstance(value, (str, int, float, bool, type(None))):
                    config_to_save[key] = value
                elif isinstance(value, (list, tuple)):
                    # Handle lists/tuples, preserving non-string items when possible
                    encoded_list = []
                    for v in value:
                        if isinstance(v, (str, int, float, bool, type(None))):
                            encoded_list.append(v)
                        elif isinstance(v, (list, dict, bytes)):
                            encoded_list.append(self._encode_binary(v))
                        else:
                            # Try to convert to string as a fallback
                            try:
                                encoded_list.append(str(v))
                            except Exception:
                                pass  # Skip items that can't be converted
                    config_to_save[key] = encoded_list
                elif isinstance(value, dict):
                    # Recursively process dictionaries
                    config_to_save[key] = self._encode_binary(value)
                elif isinstance(value, bytes):
                    # Handle binary data
                    config_to_save[key] = f"!!binary {base64.b64encode(value).decode('utf-8')}"
                else:
                    # Try to convert to string as a fallback
                    try:
                        config_to_save[key] = str(value)
                    except Exception as e:
                        logging.warning(f"Could not serialize {key}: {e}")
            
            # Save to file with explicit YAML tags for binary data
            with open(self.config_path, 'w', encoding='utf-8') as f:
                yaml.dump(config_to_save, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
                
        except Exception as e:
            logging.error(f"Error saving config to {self.config_path}: {e}")
            # Try to create a backup if the file is corrupted
            if self.config_path.exists():
                backup_path = self.config_path.with_suffix('.bak')
                try:
                    import shutil
                    shutil.copy2(self.config_path, backup_path)
                    logging.info(f"Created backup of config at {backup_path}")
                except Exception as backup_error:
                    logging.error(f"Failed to create backup: {backup_error}")
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value.
        
        Args:
            key: Configuration key in dot notation (e.g., 'settings.api_id')
            default: Default value if key is not found
            
        Returns:
            The configuration value or default if not found
        """
        keys = key.split('.')
        value = self.config
        
        try:
            for k in keys:
                value = value[k]
            return value
        except (KeyError, TypeError):
            return default
    
    def set(self, key: str, value: Any) -> None:
        """Set a configuration value.
        
        Args:
            key: Configuration key in dot notation (e.g., 'settings.api_id')
            value: Value to set
        """
        keys = key.split('.')
        current = self.config
        
        for k in keys[:-1]:
            if k not in current or not isinstance(current[k], dict):
                current[k] = {}
            current = current[k]
        
        current[keys[-1]] = value
