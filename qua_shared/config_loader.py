"""Shared config and template loader for .github/config/*.yml and docs/templates/**."""

from functools import lru_cache
from pathlib import Path

import yaml

# qua_shared/config_loader.py -> qua_shared/ -> repo root
_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_DIR = _ROOT / ".github" / "config"
_TEMPLATE_DIR = _ROOT / "docs" / "templates"


@lru_cache(maxsize=32)
def load_config(name: str) -> dict:
    with open(_CONFIG_DIR / f"{name}.yml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def template_path(name: str, ext: str = "md") -> Path:
    """Absolute path to a render-template under ``docs/templates/``."""
    return _TEMPLATE_DIR / f"{name}.{ext}"


@lru_cache(maxsize=64)
def load_template(name: str, ext: str = "md") -> str:
    return template_path(name, ext).read_text(encoding="utf-8")


def repo_config() -> dict:
    return load_config("repo")
