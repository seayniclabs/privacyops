"""Small shared helpers: input cleaning, dates, and the disclaimer."""

from __future__ import annotations

import re
from datetime import date, datetime, timezone

from .errors import PrivacyOpsError

DISCLAIMER = (
    "NOT LEGAL ADVICE. PrivacyOps is a tracking and drafting aid. It does not know your facts "
    "or the law in your state. The templates have not been reviewed by a lawyer. For legal "
    "questions, ask a lawyer or a consumer-protection agency."
)

_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def today() -> str:
    return date.today().isoformat()


def clean(value: str | None, module: str, field: str, limit: int, required: bool = False) -> str | None:
    """Strip control characters (keeping newlines and tabs), trim, and enforce a length limit."""
    text = "".join(c for c in (value or "") if c in "\n\t" or ord(c) >= 32).strip()
    if not text:
        if required:
            raise PrivacyOpsError(module, "bad_input", f"{field} is required.", f"pass {field} as text.")
        return None
    if len(text) > limit:
        raise PrivacyOpsError(module, "bad_input", f"{field} is longer than {limit} characters.",
                              "shorten it and try again.")
    return text


def parse_date(value: str | None, module: str, field: str) -> str:
    if not (isinstance(value, str) and _DATE_RE.fullmatch(value)):
        raise PrivacyOpsError(module, "bad_input", f"{field} must be a date like 2026-10-27.",
                              "use YYYY-MM-DD.")
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        raise PrivacyOpsError(module, "bad_input", f"{field} {value!r} is not a real calendar date.",
                              "use YYYY-MM-DD with a real date.")
