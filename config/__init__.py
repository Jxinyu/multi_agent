from pathlib import Path

from config.config import load_setting, validate_runtime_settings

path = Path(__file__).parent.absolute()

settings = load_setting(f"{path}/config.yaml")

__all__ = ["settings", "validate_runtime_settings"]
