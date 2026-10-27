"""PrivacyOps server: one process, one tool per module operation, plus a discovery call."""

from __future__ import annotations

import argparse

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import BaseModel

from . import __version__
from . import skills as skills_mod
from .common import DISCLAIMER
from .config import Config, config_path
from .modules import Module, all_modules
from .store import Store

PUBLISHER = "Seaynic Labs"
HOMEPAGE = "https://github.com/seayniclabs/privacyops"

INSTRUCTIONS = (
    "PrivacyOps tracks your credit-bureau and furnisher disputes, shows the statutory response deadline for each, "
    "and drafts dispute letters from fixed templates. Everything stays on this machine. " + DISCLAIMER + " "
    "Call privacyops_modules first: it says which modules are on, what each tool does, and where your data "
    "is kept. Skills (MCP prompts) explain how to do the job well; start with the getting-started prompt. "
    "Errors read 'privacyops.<module>.<code>: <message> Fix: <hint>'."
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


class SkillInfo(BaseModel):
    name: str
    description: str
    license: str


class ModulesResult(BaseModel):
    version: str
    disclaimer: str
    data_dir: str
    config_file: str
    config_error: str | None = None
    modules: list[ModuleInfo]
    skills: list[SkillInfo]
    publisher: str = PUBLISHER
    homepage: str = HOMEPAGE


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

    loaded_skills = skills_mod.register(mcp, "privacyops")

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
    def privacyops_modules(module: str | None = None) -> ModulesResult:
        """Which modules are on, what each tool does, where your data is kept, the skills, and the disclaimer.
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
            skills=[SkillInfo(name=s["name"], description=s["description"], license=s["license"])
                    for s in loaded_skills],
        )

    return mcp


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="privacyops-mcp", description=INSTRUCTIONS)
    parser.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1", help="HTTP only. Keep 127.0.0.1 unless you add auth in front.")
    parser.add_argument("--port", type=int, default=8765, help="HTTP only.")
    parser.add_argument("--version", action="version", version=f"privacyops-mcp {__version__}")
    parser.add_argument("--doctor", action="store_true",
                        help="Check the data folder, the records file and the settings, print fixes, and exit. "
                             "Makes no network calls.")
    args = parser.parse_args(argv)

    if args.doctor:
        from .doctor import run
        raise SystemExit(run())

    if args.transport == "http":
        build_server(host=args.host, port=args.port).run(transport="streamable-http")
    else:
        build_server().run(transport="stdio")


if __name__ == "__main__":
    main()
