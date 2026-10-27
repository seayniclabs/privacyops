"""Local approval log: one JSON line per approval asked, granted, declined or refused.

Written to $PRIVACYOPS_APPROVAL_LOG, or $XDG_STATE_HOME/privacyops/approvals.jsonl
(~/.local/state/privacyops/approvals.jsonl). It never leaves the machine.

Only identifiers are logged (the tool name, the dispute id, who decided, and a reason
code). Dispute contents are never logged: not the party, the item, the reason, the notes
or the letter text.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Mapping

DECISIONS = ("requested", "approved", "declined", "refused")


def log_path(env: Mapping[str, str]) -> Path:
    if env.get("PRIVACYOPS_APPROVAL_LOG"):
        return Path(env["PRIVACYOPS_APPROVAL_LOG"]).expanduser()
    base = env.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "privacyops" / "approvals.jsonl"


def record(env: Mapping[str, str], tool: str, decision: str, by: str | None, details: dict) -> None:
    """decision: requested | approved | declined | refused. Never raises: logging must not block a delete.

    ``details`` may hold identifiers only. Callers pass ``{"dispute_id": ...}`` and a short ``reason`` code.
    """
    if decision not in DECISIONS:
        raise ValueError(f"unknown approval decision {decision!r}")
    try:
        path = log_path(env)
        path.parent.mkdir(parents=True, exist_ok=True)
        line = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "tool": tool,
                "decision": decision, "approved_by": by, **details}
        # Created owner-only from the start, so there is no moment when other users can read it.
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(line, ensure_ascii=False) + "\n")
        os.chmod(path, 0o600)
    except OSError:
        pass
