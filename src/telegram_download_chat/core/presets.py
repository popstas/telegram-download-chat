"""Preset management helpers."""

from typing import Any, Dict, List

from telegram_download_chat.gui.utils import ConfigManager


def load_presets() -> List[Dict[str, Any]]:
    """Load presets from the configuration file."""
    cfg = ConfigManager()
    cfg.load()
    presets = cfg.get("presets", [])
    if isinstance(presets, dict):
        return [{"name": k, "args": v} for k, v in presets.items()]
    return presets if isinstance(presets, list) else []


def save_presets(presets: List[Dict[str, Any]]) -> None:
    """Save presets to the configuration file."""
    cfg = ConfigManager()
    cfg.load()
    cfg.set("presets", presets)
    cfg.save()


def add_preset(name: str, args: Dict[str, Any]) -> None:
    """Add or replace a preset in the configuration."""
    presets = load_presets()
    for preset in presets:
        if preset.get("name") == name:
            preset["args"] = args
            break
    else:
        presets.append({"name": name, "args": args})
    save_presets(presets)


def remove_preset(name: str) -> None:
    """Remove a preset from the configuration."""
    presets = [p for p in load_presets() if p.get("name") != name]
    save_presets(presets)


def apply_preset(preset: Dict[str, Any], args: Any) -> Any:
    """Apply values from *preset* to *args* object.

    Parameters
    ----------
    preset:
        Dictionary with argument overrides.
    args:
        Object to update. Attributes matching the keys in ``preset`` will be
        replaced. The object is returned for convenience.
    """

    for key, value in preset.items():
        if hasattr(args, key):
            setattr(args, key, value)
        elif isinstance(args, dict):
            args[key] = value

    return args


def is_preset_modified(preset: Dict[str, Any], args: Any) -> bool:
    """Return ``True`` if *args* differs from *preset* values."""

    for key, value in preset.items():
        current = None
        if hasattr(args, key):
            current = getattr(args, key)
        elif isinstance(args, dict):
            current = args.get(key)
        if current != value:
            return True
    return False
