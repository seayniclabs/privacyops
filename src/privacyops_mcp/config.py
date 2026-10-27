"""Settings come from environment variables, then an optional TOML file.

Environment variables win. The file is ``$PRIVACYOPS_CONFIG`` if set, otherwise
``$XDG_CONFIG_HOME/privacyops/config.toml`` (``~/.config/privacyops/config.toml``).
Top-level keys are global (``data_dir``). Each module reads its own ``[<module>]`` table.
Nothing here assumes a particular MCP client.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Mapping

TRUE = {"1", "true", "yes", "on"}
FALSE = {"0", "false", "no", "off"}


def config_path(env: Mapping[str, str]) -> Path:
    if env.get("PRIVACYOPS_CONFIG"):
        return Path(env["PRIVACYOPS_CONFIG"]).expanduser()
    base = env.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "privacyops" / "config.toml"


def default_data_dir(env: Mapping[str, str]) -> Path:
    base = env.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "privacyops"


class Config:
    def __init__(self, env: Mapping[str, str] | None = None, file_data: dict | None = None):
        self.env = dict(os.environ if env is None else env)
        self.path = config_path(self.env)
        self.file_error: str | None = None
        if file_data is None:
            file_data = {}
            if self.path.is_file():
                try:
                    file_data = tomllib.loads(self.path.read_text(encoding="utf-8"))
                except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as e:
                    self.file_error = (
                        f"{self.path} could not be read ({type(e).__name__}); its settings were ignored."
                    )
        self.file = file_data

    def data_dir(self) -> Path:
        value = self.get_global("data_dir")
        return Path(value).expanduser() if value else default_data_dir(self.env)

    def get_global(self, key: str) -> str | None:
        value = self.env.get(f"PRIVACYOPS_{key.upper()}")
        if value not in (None, ""):
            return value
        value = self.file.get(key)
        if value not in (None, ""):
            return str(value)
        return None

    def get(self, module: str, key: str, default: str | None = None) -> str | None:
        value = self.env.get(f"PRIVACYOPS_{module.upper()}_{key.upper()}")
        if value not in (None, ""):
            return value
        table = self.file.get(module, {})
        value = table.get(key) if isinstance(table, dict) else None
        if value not in (None, ""):
            return str(value)
        return default

    def flag(self, module: str, key: str, default: bool) -> bool:
        value = self.get(module, key)
        if value is None:
            return default
        value = value.strip().lower()
        if value in TRUE:
            return True
        if value in FALSE:
            return False
        return default

    def enabled(self, module: str, default: bool) -> bool:
        return self.flag(module, "enabled", default)
