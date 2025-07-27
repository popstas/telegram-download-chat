import asyncio
import logging
import sys
from typing import Any, Dict

import yaml

from ..paths import (
    ensure_app_dirs,
    get_app_dir,
    get_default_config,
    get_default_config_path,
)


class ConfigMixin:
    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from YAML file or create default if not exists."""
        from telegram_download_chat.core import Path

        ensure_app_dirs()

        if not self.config_path:
            self.config_path = str(get_default_config_path())

        config_path = Path(self.config_path)
        default_config = get_default_config()

        if not config_path.exists():
            try:
                config_path.parent.mkdir(parents=True, exist_ok=True)
                with open(config_path, "w", encoding="utf-8") as f:
                    yaml.safe_dump(default_config, f, default_flow_style=False)
                logging.info(f"Created default config at {config_path}")
                print("\n" + "=" * 80)
                print("First run configuration:")
                print("1. Go to https://my.telegram.org/apps")
                print("2. Create a new application")
                print("3. Copy API ID and API Hash")
                print(f"4. Edit the config file at: {config_path}")
                print(
                    "5. Replace 'YOUR_API_ID' and 'YOUR_API_HASH' with your credentials"
                )
                print("=" * 80 + "\n")
                return default_config
            except Exception as e:
                logging.error(f"Failed to create default config: {e}")
                return default_config

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                loaded_config = yaml.safe_load(f) or {}

            if "api_id" in loaded_config or "api_hash" in loaded_config:
                if "settings" not in loaded_config:
                    loaded_config["settings"] = {}
                if "api_id" in loaded_config:
                    loaded_config["settings"]["api_id"] = loaded_config.pop("api_id")
                if "api_hash" in loaded_config:
                    loaded_config["settings"]["api_hash"] = loaded_config.pop(
                        "api_hash"
                    )

                with open(config_path, "w", encoding="utf-8") as f:
                    yaml.safe_dump(loaded_config, f, default_flow_style=False)

            return self._merge_configs(default_config, loaded_config)

        except yaml.YAMLError as e:
            logging.error(f"Error loading config from {config_path}: {e}")
            return default_config

    def _merge_configs(
        self, default: Dict[str, Any], custom: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Recursively merge two configuration dictionaries."""
        result = default.copy()
        for key, value in custom.items():
            if (
                key in result
                and isinstance(result[key], dict)
                and isinstance(value, dict)
            ):
                result[key] = self._merge_configs(result[key], value)
            else:
                result[key] = value
        return result

    def _setup_logging(self) -> None:
        from telegram_download_chat.core import Path

        """Configure logging based on config."""
        log_level = self.config.get("settings", {}).get("log_level", "INFO")
        log_file = self.config.get("settings", {}).get(
            "log_file", get_app_dir() / "app.log"
        )

        if log_file:
            log_path = Path(log_file)
            log_path.parent.mkdir(parents=True, exist_ok=True)

        root_logger = logging.getLogger()
        root_logger.setLevel(logging.WARNING)
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)

        self.logger = logging.getLogger("telegram_download_chat")
        self.logger.setLevel(getattr(logging, log_level.upper()))

        formatter = logging.Formatter(
            "%(asctime)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
        )

        if log_file:
            file_handler = logging.FileHandler(log_file, encoding="utf-8")
            file_handler.setFormatter(formatter)
            self.logger.addHandler(file_handler)

        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setFormatter(formatter)
        self.logger.addHandler(console_handler)
        self.logger.propagate = False

        logging.getLogger("telethon").setLevel(logging.WARNING)
        logging.getLogger("asyncio").setLevel(logging.WARNING)

        from telegram_download_chat.core import Path

    def _save_config(self) -> None:
        """Save the current config to the config file."""
        with open(self.config_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(self.config, f, allow_unicode=True)
