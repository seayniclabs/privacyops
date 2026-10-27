"""`privacyops-mcp --doctor`: check the data folder, the records file and the settings, and print a fix for each problem.

It reads files and never changes them: each FIX line names the step to take. It makes no network calls
and creates no files (not even the lock file the server uses). Exit status 0 = ready, 1 = something to fix.
"""

from __future__ import annotations

import json
import os
import stat
import sys
from datetime import date
from pathlib import Path

from . import __version__
from .approvals import log_path
from .config import Config, config_path
from .modules import all_modules

STATUSES = {"draft", "sent", "response_received", "resolved", "closed"}
PARTY_TYPES = {"consumer_reporting_agency", "furnisher"}
REQUIRED_KEYS = ("id", "party_type", "party_name", "item_description", "status", "created_at", "updated_at", "history")
PRIVATE_MASK = 0o077  # group and other bits must be zero


def _loose(path: Path) -> bool:
    return os.name != "nt" and bool(stat.S_IMODE(path.stat().st_mode) & PRIVATE_MASK)


def _record_problems(data: dict, letters_dir: Path) -> list[str]:
    """Problems found in the records, described by record id only. Never includes names or text."""
    problems: list[str] = []
    for key, rec in data["disputes"].items():
        if not isinstance(rec, dict):
            problems.append(f"{key}: record is not an object")
            continue
        missing = [k for k in REQUIRED_KEYS if k not in rec]
        if missing:
            problems.append(f"{key}: missing {', '.join(missing)}")
            continue
        if rec["id"] != key:
            problems.append(f"{key}: stored under a different id")
        if rec["party_type"] not in PARTY_TYPES:
            problems.append(f"{key}: unknown party_type")
        if rec["status"] not in STATUSES:
            problems.append(f"{key}: unknown status")
        if not isinstance(rec["history"], list):
            problems.append(f"{key}: history is not a list")
        for field in ("sent_date", "due_date"):
            value = rec.get(field)
            if value is not None:
                try:
                    date.fromisoformat(value)
                except (TypeError, ValueError):
                    problems.append(f"{key}: {field} is not a date")
        for name in rec.get("letter_files", []) or []:
            if not isinstance(name, str) or "/" in name or name.startswith("."):
                problems.append(f"{key}: a letter file name is not a plain file name")
            elif not (letters_dir / name).is_file():
                problems.append(f"{key}: letter file {name} is listed but missing from the letters folder")
    return problems


def _checks(config: Config) -> list[tuple[str, bool, str]]:
    out: list[tuple[str, bool, str]] = []
    cfg_path = config_path(config.env)
    if config.file_error:
        out.append(("config file", False, f"{config.file_error} Fix: correct the TOML in {cfg_path}."))
    else:
        out.append(("config file", True, f"{cfg_path} ({'found' if cfg_path.is_file() else 'not used'})"))

    data_dir = config.data_dir()
    letters_dir = data_dir / "letters"
    if not data_dir.exists():
        out.append(("data folder", True, f"{data_dir} (not created yet; the first save creates it, owner-only)"))
    elif not data_dir.is_dir():
        out.append(("data folder", False, f"{data_dir} is not a folder. Fix: set PRIVACYOPS_DATA_DIR to a folder."))
    elif not os.access(data_dir, os.W_OK | os.X_OK):
        out.append(("data folder", False, f"{data_dir} is not writable. Fix: give your user write access, or set PRIVACYOPS_DATA_DIR."))
    elif _loose(data_dir):
        out.append(("data folder", False, f"{data_dir} is readable by other users. Fix: chmod 700 {data_dir}"))
    else:
        out.append(("data folder", True, f"{data_dir} (owner-only)"))

    records = data_dir / "privacyops.json"
    if not records.exists():
        out.append(("records", True, "no records yet"))
    else:
        try:
            data = json.loads(records.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or not isinstance(data.get("disputes"), dict):
                raise ValueError("unexpected structure")
        except (OSError, UnicodeDecodeError, ValueError) as e:
            out.append(("records", False,
                        f"{records.name} cannot be read ({type(e).__name__}). Fix: move it aside and restore a backup. "
                        "PrivacyOps never overwrites a file it cannot read."))
        else:
            problems = _record_problems(data, letters_dir)
            count = len(data["disputes"])
            if problems:
                shown = "; ".join(problems[:3])
                more = f" (and {len(problems) - 3} more)" if len(problems) > 3 else ""
                out.append(("records", False, f"{count} record(s), {len(problems)} problem(s): {shown}{more}. "
                                              "Fix: restore the affected records from a backup, or delete them with disputes_delete."))
            else:
                out.append(("records", True, f"{count} record(s), all valid"))
        if _loose(records):
            out.append(("records file", False, f"{records} is readable by other users. Fix: chmod 600 {records}"))

    if letters_dir.exists() and _loose(letters_dir):
        out.append(("letters", False, f"{letters_dir} is readable by other users. Fix: chmod 700 {letters_dir}"))
    elif letters_dir.exists():
        out.append(("letters", True, f"{len(list(letters_dir.glob('*.md')))} letter file(s), owner-only"))
    else:
        out.append(("letters", True, "no letters yet"))

    log = log_path(config.env)
    if log.exists() and not os.access(log, os.W_OK):
        out.append(("approval log", False, f"{log} is not writable. Fix: give your user write access or set PRIVACYOPS_APPROVAL_LOG."))
    else:
        out.append(("approval log", True, f"{log} (one line per delete decision; ids only)"))

    for m in all_modules():
        on = config.enabled(m.name, m.default_enabled)
        out.append((f"module:{m.name}", True, "on" if on else "off (its tools are not offered)"))
    if config.flag("disputes", "allow_delete", False):
        out.append(("deletes", True, "pre-approved in settings (PRIVACYOPS_DISPUTES_ALLOW_DELETE=true)"))
    else:
        out.append(("deletes", True, "each delete needs your approval in your MCP app"))
    return out


def run(config: Config | None = None) -> int:
    config = config or Config()
    results = _checks(config)
    print(f"privacyops-mcp {__version__} doctor")
    for name, ok, msg in results:
        print(f"  {'ok ' if ok else 'FIX'}  {name:<14} {msg}")
    bad = sum(1 for _, ok, _ in results if not ok)
    print("ready" if not bad else f"{bad} thing(s) to fix")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(run())
