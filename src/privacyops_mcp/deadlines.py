"""Response deadlines for open disputes, counted from the statute.

Every period below was checked against the official statute text on 2026-10-27:

- https://www.law.cornell.edu/uscode/text/15/1681i
  (a)(1)(A): the agency must reinvestigate "before the end of the 30-day period beginning on the date on
  which the agency receives the notice of the dispute".
  (a)(1)(B): that period "may be extended for not more than 15 additional days" if the agency receives
  relevant information from the consumer during the 30 days.
  (a)(1)(C): no extension if, during the 30 days, the item is found inaccurate or incomplete or cannot be
  verified.
- https://www.law.cornell.edu/uscode/text/15/1681s-2
  (a)(8)(E)(iii): a furnisher that receives a direct dispute must report the results "before the expiration
  of the period under section 1681i(a)(1)".
  (b)(2): a furnisher that receives a dispute forwarded by an agency must finish "before the expiration of
  the period under section 1681i(a)(1)".

The tool counts from the sent date you record. The statute counts from the day the other side receives the
dispute, so the real deadline is the same or later. The tool never guesses at the start of the clock, at
whether an extension applies, or at a frivolous-dispute decision: it names those facts in ``unknowns``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

CHECKED = "2026-10-27"
BASE_DAYS = 30
EXTENSION_DAYS = 15
OPEN_STATUSES = ("draft", "sent", "response_received")

SOURCES = (
    ("15 U.S.C. 1681i(a)(1)", "https://www.law.cornell.edu/uscode/text/15/1681i",
     "30 days from when the agency receives the dispute; up to 15 more days only if relevant information arrives in that window."),
    ("15 U.S.C. 1681s-2(a)(8)(E)(iii), (b)(2)", "https://www.law.cornell.edu/uscode/text/15/1681s-2",
     "A furnisher must report results before the 1681i(a)(1) period ends."),
)


@dataclass(frozen=True)
class Plan:
    cite: str
    due: date | None
    extended_due: date | None
    clock_starts: str
    unknowns: tuple[str, ...]


def plan_for(party_type: str, sent: date | None) -> Plan:
    """The statutory period for one dispute, counted from the recorded sent date."""
    if party_type == "furnisher":
        return Plan(
            cite="15 U.S.C. 1681s-2(a)(8)(E)(iii) for a direct dispute; 1681s-2(b)(2) for a dispute an agency forwarded",
            due=sent + timedelta(days=BASE_DAYS) if sent else None,
            extended_due=None,
            clock_starts="the day the furnisher receives your dispute (or the agency's notice). The tool counts from your sent date.",
            unknowns=(
                "Which route your dispute took: sent straight to the furnisher, or forwarded by an agency. "
                "The clock runs from the furnisher's receipt either way, and you cannot see that date.",
                "The statute does not say whether the 15-day extension in 1681i(a)(1)(B) applies to a furnisher, "
                "so no extended date is shown.",
            ),
        )
    return Plan(
        cite="15 U.S.C. 1681i(a)(1)(A)",
        due=sent + timedelta(days=BASE_DAYS) if sent else None,
        extended_due=sent + timedelta(days=BASE_DAYS + EXTENSION_DAYS) if sent else None,
        clock_starts="the day the agency receives your dispute. The tool counts from your sent date, so the real deadline is the same or later.",
        unknowns=(
            "When the agency actually received the letter (mail can take days).",
            "Whether you sent relevant information during the first 30 days. If you did, the agency may take up to "
            "15 more days (1681i(a)(1)(B)). It may not extend if it found the item inaccurate or could not verify it "
            "in those 30 days (1681i(a)(1)(C)).",
        ),
    )


@dataclass(frozen=True)
class Assessment:
    due: date | None
    extended_due: date | None
    days_remaining: int | None
    overdue: bool
    next_action: str


def next_action(status: str, sent: date | None, plan: Plan, as_of: date) -> Assessment:
    due, extended = plan.due, plan.extended_due
    days = (due - as_of).days if due else None
    if status == "draft":
        return Assessment(None, None, None, False,
                          "Send the letter, then record the date with disputes_update (status sent, sent_date).")
    if status == "response_received":
        return Assessment(due, extended, days, False,
                          "Read the response. If the item is still wrong, add a note with disputes_update and choose the next letter.")
    if sent is None or due is None:
        return Assessment(None, None, None, False,
                          "Record the sent date with disputes_update so a due date can be counted.")
    if as_of <= due:
        return Assessment(due, extended, days, False,
                          f"Wait for the response, due by {due.isoformat()}. If nothing arrives by then, send a written "
                          "follow-up and log it with disputes_update.")
    if extended and as_of <= extended:
        return Assessment(due, extended, days, True,
                          f"Past the 30-day date ({due.isoformat()}). The 45-day date ({extended.isoformat()}) applies only if "
                          "you sent relevant information in the first 30 days. If you did not, send a written follow-up now "
                          "and log it.")
    return Assessment(due, extended, days, True,
                      "Past the deadline. Send a written follow-up now, keep proof of mailing, and log it with disputes_update.")


def assess(rec: dict[str, Any], as_of: date) -> dict[str, Any]:
    """One row for disputes_deadlines. ``rec`` is a stored dispute record."""
    sent = date.fromisoformat(rec["sent_date"]) if rec.get("sent_date") else None
    plan = plan_for(rec["party_type"], sent)
    result = next_action(rec["status"], sent, plan, as_of)
    return {
        "id": rec["id"],
        "party_type": rec["party_type"],
        "party_name": rec["party_name"],
        "status": rec["status"],
        "sent_date": rec.get("sent_date"),
        "due_date": result.due.isoformat() if result.due else None,
        "extended_due_date": result.extended_due.isoformat() if result.extended_due else None,
        "days_remaining": result.days_remaining,
        "overdue": result.overdue,
        "next_action": result.next_action,
        "basis": plan.cite,
        "clock_starts": plan.clock_starts,
        "unknowns": list(plan.unknowns),
    }
