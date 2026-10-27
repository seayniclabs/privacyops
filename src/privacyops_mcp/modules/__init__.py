"""Module contract and registry.

A module is one feature area (disputes, letters). It declares its settings and registers its
tools on the shared server. Adding a module means adding a file here and listing it in
``all_modules``. Modules added after 0.1 must set ``default_enabled = False`` so an update
never turns on something the person did not choose.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from mcp.server.fastmcp import FastMCP

from ..config import Config
from ..store import Store


@dataclass(frozen=True)
class Setting:
    key: str
    help: str
    kind: str = "text"  # "text" or "bool"

    def env_var(self, module: str) -> str:
        return f"PRIVACYOPS_{module.upper()}_{self.key.upper()}"


@dataclass
class Module:
    name: str
    summary: str
    settings: list[Setting]
    default_enabled: bool = True
    tools: dict[str, str] = field(default_factory=dict)  # tool name -> one-line purpose

    def register(self, mcp: FastMCP, config: Config, store: Store) -> None:
        raise NotImplementedError


def all_modules() -> list[Module]:
    from .disputes import DisputesModule
    from .letters import LettersModule

    return [DisputesModule(), LettersModule()]
