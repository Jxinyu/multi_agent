from config.config import load_setting
from pathlib import Path

path = Path(__file__).parent.absolute()

settings = load_setting(f"{path}/config.yaml")
