"""Shared config and template loader for .github/config/*.yml and .github/templates/**."""
import yaml
from pathlib import Path
from functools import lru_cache

# qua_shared/config_loader.py -> qua_shared/ -> repo root
_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_DIR = _ROOT / ".github" / "config"
_TEMPLATE_DIR = _ROOT / ".github" / "templates"


@lru_cache(maxsize=32)
def load_config(name: str) -> dict:
    with open(_CONFIG_DIR / f"{name}.yml", encoding="utf-8") as f:
        return yaml.safe_load(f)


@lru_cache(maxsize=64)
def load_template(name: str, ext: str = "md") -> str:
    return (_TEMPLATE_DIR / f"{name}.{ext}").read_text(encoding="utf-8")


def repo_config() -> dict:
    return load_config("repo")
