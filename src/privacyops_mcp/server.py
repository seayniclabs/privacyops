"""PrivacyOps server: one process, one tool per module operation, plus a discovery call."""

from __future__ import annotations

import argparse

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import BaseModel

from . import __version__
from .common import DISCLAIMER
from .config import Config, config_path
from .modules import Module, all_modules
from .store import Store

INSTRUCTIONS = (
    "PrivacyOps tracks your credit-bureau and furnisher disputes and drafts dispute letters from fixed "
    "templates. Everything stays on this machine. " + DISCLAIMER + " "
    "Call privacyops_modules first: it says which modules are on, what each tool does, and where your data "
    "is kept. Errors read 'privacyops.<module>.<code>: <message> Fix: <hint>'."
)


class SettingInfo(BaseModel):
    env_var: str
    help: str
    set: bool


class ModuleInfo(BaseModel):
    name: str
    summary: str
    enabled: bool
    tools: dict[str, str]
    settings: list[SettingInfo] | None = None


class ModulesResult(BaseModel):
    version: str
    disclaimer: str
    data_dir: str
    config_file: str
    config_error: str | None = None
    modules: list[ModuleInfo]


def build_server(
    config: Config | None = None,
    modules: list[Module] | None = None,
    store: Store | None = None,
    **settings,
) -> FastMCP:
    config = config or Config()
    modules = modules if modules is not None else all_modules()
    store = store or Store(config.data_dir())
    mcp = FastMCP("privacyops", instructions=INSTRUCTIONS, **settings)
    # FastMCP 1.x reports the SDK's version unless the low-level server is told otherwise.
    mcp._mcp_server.version = __version__

    for module in modules:
        if config.enabled(module.name, module.default_enabled):
            module.register(mcp, config, store)

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
    def privacyops_modules(module: str | None = None) -> ModulesResult:
        """Which modules are on, what each tool does, where your data is kept, and the disclaimer.
        Pass a module name for its full settings list."""
        infos = []
        for m in modules:
            if module and m.name != module:
                continue
            info = ModuleInfo(
                name=m.name, summary=m.summary, enabled=config.enabled(m.name, m.default_enabled), tools=m.tools,
            )
            if module:
                info.settings = [
                    SettingInfo(env_var=s.env_var(m.name), help=s.help, set=bool(config.get(m.name, s.key)))
                    for s in m.settings
                ]
            infos.append(info)
        return ModulesResult(
            version=__version__, disclaimer=DISCLAIMER, data_dir=str(store.dir),
            config_file=str(config_path(config.env)), config_error=config.file_error, modules=infos,
        )

    return mcp


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="privacyops-mcp", description=INSTRUCTIONS)
    parser.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1", help="HTTP only. Keep 127.0.0.1 unless you add auth in front.")
    parser.add_argument("--port", type=int, default=8765, help="HTTP only.")
    parser.add_argument("--version", action="version", version=f"privacyops-mcp {__version__}")
    args = parser.parse_args(argv)

    if args.transport == "http":
        build_server(host=args.host, port=args.port).run(transport="streamable-http")
    else:
        build_server().run(transport="stdio")


if __name__ == "__main__":
    main()
