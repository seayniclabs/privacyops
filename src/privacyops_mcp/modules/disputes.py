"""Disputes: track disputes with consumer reporting agencies and with furnishers.

A furnisher is the company that reports information about you to an agency. Records live in
the local store. Deleting a record needs the person's approval: asked through MCP elicitation,
or pre-approved with PRIVACYOPS_DISPUTES_ALLOW_DELETE=true.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any, Literal

from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from .. import approvals
from ..common import DISCLAIMER, clean, now_iso, parse_date, today
from ..config import Config
from ..deadlines import CHECKED, OPEN_STATUSES, SOURCES, assess
from ..errors import PrivacyOpsError
from ..store import Store
from . import Module, Setting

PartyType = Literal["consumer_reporting_agency", "furnisher"]
Status = Literal["draft", "sent", "response_received", "resolved", "closed"]

READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
WRITES_LOCAL = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)
DELETES = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False)

DUE_CRA = (
    "30 days from when the agency receives the dispute (15 U.S.C. 1681i(a)(1)(A)). sent_date is only "
    "an estimate of that day. This tool does not model any exception or extension."
)
DUE_FURNISHER = (
    "The furnisher must complete its investigation and report the results before the period in "
    "15 U.S.C. 1681i(a)(1)(A) ends (15 U.S.C. 1681s-2(a)(8)(E)). This tool does not compute that date."
)
NO_DATE = "Set sent_date to see the 30-day due date (15 U.S.C. 1681i(a)(1)(A))."

LIMITS = {"party_name": 120, "item_description": 2000, "reason": 2000, "note": 2000}


class HistoryEntry(BaseModel):
    at: str
    action: str = Field(description="created, status, sent_date, note, or letter")
    from_status: str | None = None
    to_status: str | None = None
    note: str | None = None


class Dispute(BaseModel):
    id: str
    party_type: PartyType
    party_name: str
    item_description: str
    reason: str | None = None
    status: Status
    sent_date: str | None = None
    due_date: str | None = None
    due_note: str
    letter_files: list[str] = Field(default_factory=list)
    created_at: str
    updated_at: str
    history: list[HistoryEntry] = Field(default_factory=list)


class DisputeSummary(BaseModel):
    id: str
    party_type: PartyType
    party_name: str
    status: Status
    sent_date: str | None = None
    due_date: str | None = None
    updated_at: str


class DisputePage(BaseModel):
    disputes: list[DisputeSummary]
    total: int
    has_more: bool
    next_offset: int | None = None


class DeleteResult(BaseModel):
    deleted: bool
    id: str
    approved_by: str | None = None  # "person", "settings", or None
    preview: DisputeSummary | None = None
    note: str | None = None


class DeleteApproval(BaseModel):
    delete: bool = Field(description="Permanently delete this dispute record?")


class RuleSource(BaseModel):
    cite: str
    url: str
    checked: str = Field(description="Date the official text was checked.")
    says: str


class DeadlineRow(BaseModel):
    id: str
    party_type: PartyType
    party_name: str
    status: Status
    sent_date: str | None = None
    due_date: str | None = Field(None, description="Sent date + 30 days. Counted from the sent date, not receipt.")
    extended_due_date: str | None = Field(None, description="Sent date + 45 days. Only if relevant information was "
                                                           "sent in the first 30 days; agencies only.")
    days_remaining: int | None = Field(None, description="Negative when past due_date.")
    overdue: bool = Field(description="True when a sent dispute is past its 30-day date.")
    next_action: str
    basis: str
    clock_starts: str
    unknowns: list[str] = Field(description="Facts the tool cannot know, so it does not guess them.")


class DeadlinePage(BaseModel):
    as_of: str
    disclaimer: str
    sources: list[RuleSource]
    open_total: int
    overdue_total: int
    disputes: list[DeadlineRow]
    has_more: bool
    next_offset: int | None = None


def due_for(party_type: str, sent_date: str | None) -> tuple[str | None, str]:
    if party_type == "furnisher":
        return None, DUE_FURNISHER
    if sent_date:
        due = date.fromisoformat(sent_date) + timedelta(days=30)
        return due.isoformat(), DUE_CRA
    return None, NO_DATE


def summarize(rec: dict[str, Any]) -> DisputeSummary:
    return DisputeSummary(
        id=rec["id"], party_type=rec["party_type"], party_name=rec["party_name"], status=rec["status"],
        sent_date=rec.get("sent_date"), due_date=rec.get("due_date"), updated_at=rec["updated_at"],
    )


def _can_ask_person(ctx: Context) -> bool:
    try:
        caps = ctx.session.client_params.capabilities  # type: ignore[union-attr]
    except (ValueError, AttributeError):
        return False
    return bool(caps and caps.elicitation)


def _get(data: dict, dispute_id: str) -> dict:
    rec = data["disputes"].get(dispute_id)
    if rec is None:
        raise PrivacyOpsError("disputes", "not_found", f"no dispute with id {dispute_id!r}.",
                              "call privacyops_list or disputes_list to find the id.")
    return rec


class DisputesModule(Module):
    def __init__(self) -> None:
        super().__init__(
            name="disputes",
            summary="Track disputes with credit-reporting agencies and furnishers: status, sent dates, "
                    "30-day due dates, and history.",
            settings=[
                Setting("allow_delete", "true lets the assistant delete a dispute record without asking "
                        "you each time. Default false: you approve each delete.", kind="bool"),
            ],
            tools={
                "disputes_list": "List disputes, filtered and paged.",
                "disputes_get": "Full record for one dispute, with its history.",
                "disputes_create": "Start tracking a dispute.",
                "disputes_update": "Change status, set the sent date, or add a note. Keeps history.",
                "disputes_deadlines": "Open disputes with the statutory response deadline for each, days remaining, "
                                      "an overdue flag and the next action. Read-only.",
                "disputes_delete": "Delete a dispute record. Preview first; you approve it.",
            },
        )

    def register(self, mcp: FastMCP, config: Config, store: Store) -> None:
        allow_delete = config.flag("disputes", "allow_delete", False)

        @mcp.tool(annotations=READ_ONLY)
        def disputes_list(status: Status | None = None, party_type: PartyType | None = None,
                          limit: int = 20, offset: int = 0) -> DisputePage:
            """List disputes, newest first. Filter by status or party_type. Page with offset=<next_offset>."""
            limit = max(1, min(limit, 100))
            offset = max(0, offset)
            data = store.read()
            rows = [r for r in data["disputes"].values()
                    if (status is None or r["status"] == status)
                    and (party_type is None or r["party_type"] == party_type)]
            rows.sort(key=lambda r: r["created_at"], reverse=True)
            page = rows[offset:offset + limit]
            has_more = offset + limit < len(rows)
            return DisputePage(disputes=[summarize(r) for r in page], total=len(rows),
                               has_more=has_more, next_offset=offset + limit if has_more else None)

        @mcp.tool(annotations=READ_ONLY)
        def disputes_get(id: str) -> Dispute:
            """The full record for one dispute: details, due date, letters written, and history."""
            return Dispute.model_validate(_get(store.read(), id))

        @mcp.tool(annotations=READ_ONLY)
        def disputes_deadlines(as_of: str | None = None, limit: int = 20, offset: int = 0) -> DeadlinePage:
            """Open disputes (draft, sent, response_received) with the statutory response deadline for each.
            An agency must reinvestigate within 30 days of receiving the dispute, 15 U.S.C. 1681i(a)(1)(A)
            (https://www.law.cornell.edu/uscode/text/15/1681i). A furnisher must report results before that
            period ends, 15 U.S.C. 1681s-2(a)(8)(E)(iii) and (b)(2) (https://www.law.cornell.edu/uscode/text/15/1681s-2).
            Counted from the sent date you recorded, so the real date is the same or later. Returns days remaining,
            an overdue flag (past the 30-day date), the next action, and the facts the tool cannot know (the start
            of the clock, the 15-day extension, a furnisher's extension). Not legal advice. Set as_of (YYYY-MM-DD) to
            check another day. Page with offset=<next_offset>."""
            day = parse_date(as_of, "disputes", "as_of") if as_of else today()
            limit = max(1, min(limit, 100))
            offset = max(0, offset)
            data = store.read()
            rows = [r for r in data["disputes"].values() if r["status"] in OPEN_STATUSES]
            items = [assess(r, date.fromisoformat(day)) for r in rows]
            items.sort(key=lambda a: (a["due_date"] is None, a["due_date"] or "", a["id"]))
            page = items[offset:offset + limit]
            has_more = offset + limit < len(items)
            return DeadlinePage(
                as_of=day, disclaimer=DISCLAIMER,
                sources=[RuleSource(cite=c, url=u, checked=CHECKED, says=s) for c, u, s in SOURCES],
                open_total=len(items), overdue_total=sum(1 for a in items if a["overdue"]),
                disputes=[DeadlineRow.model_validate(a) for a in page],
                has_more=has_more, next_offset=offset + limit if has_more else None,
            )

        @mcp.tool(annotations=WRITES_LOCAL)
        def disputes_create(party_type: PartyType, party_name: str, item_description: str,
                            reason: str | None = None, status: Status = "draft",
                            sent_date: str | None = None) -> Dispute:
            """Start tracking a dispute. party_type is consumer_reporting_agency or furnisher.
            Use the item's description, not full account numbers."""
            name = clean(party_name, "disputes", "party_name", LIMITS["party_name"], required=True)
            item = clean(item_description, "disputes", "item_description", LIMITS["item_description"], required=True)
            why = clean(reason, "disputes", "reason", LIMITS["reason"])
            sent = parse_date(sent_date, "disputes", "sent_date") if sent_date else None
            if status == "sent" and sent is None:
                sent = today()
            due, due_note = due_for(party_type, sent)
            stamp = now_iso()
            rec = {
                "id": uuid.uuid4().hex[:12], "party_type": party_type, "party_name": name,
                "item_description": item, "reason": why, "status": status, "sent_date": sent,
                "due_date": due, "due_note": due_note, "letter_files": [],
                "created_at": stamp, "updated_at": stamp,
                "history": [{"at": stamp, "action": "created", "to_status": status, "note": None}],
            }
            store.update(lambda d: d["disputes"].__setitem__(rec["id"], rec))
            return Dispute.model_validate(rec)

        @mcp.tool(annotations=WRITES_LOCAL)
        def disputes_update(id: str, status: Status | None = None, sent_date: str | None = None,
                            note: str | None = None) -> Dispute:
            """Change a dispute's status, set its sent date, or add a note. Every change is recorded in history.
            Setting status to sent without a sent date uses today's date."""
            if status is None and sent_date is None and note is None:
                raise PrivacyOpsError("disputes", "bad_input", "nothing to change.",
                                      "pass status, sent_date, or note.")
            new_sent = parse_date(sent_date, "disputes", "sent_date") if sent_date else None
            new_note = clean(note, "disputes", "note", LIMITS["note"])

            def apply(data: dict) -> dict:
                rec = _get(data, id)
                stamp = now_iso()
                sent_to_set = new_sent
                if status is not None and status != rec["status"]:
                    rec["history"].append({"at": stamp, "action": "status", "from_status": rec["status"],
                                           "to_status": status, "note": None})
                    rec["status"] = status
                    if status == "sent" and not rec.get("sent_date") and sent_to_set is None:
                        sent_to_set = today()
                if sent_to_set is not None and sent_to_set != rec.get("sent_date"):
                    rec["sent_date"] = sent_to_set
                    rec["history"].append({"at": stamp, "action": "sent_date", "note": f"sent {sent_to_set}"})
                    rec["due_date"], rec["due_note"] = due_for(rec["party_type"], sent_to_set)
                if new_note:
                    rec["history"].append({"at": stamp, "action": "note", "note": new_note})
                rec["updated_at"] = stamp
                return rec

            return Dispute.model_validate(store.update(apply))

        @mcp.tool(annotations=DELETES)
        async def disputes_delete(ctx: Context, id: str, confirm: bool = False) -> DeleteResult:
            """Delete a dispute record. Without confirm=true this only returns a preview. With confirm=true
            the person is asked to approve (unless deletes are pre-approved in settings). Letter files on
            disk are not deleted. The assistant cannot approve on the person's behalf."""
            rec = _get(store.read(), id)
            shown = summarize(rec)
            if not confirm:
                return DeleteResult(deleted=False, id=id, preview=shown,
                                    note="Preview only. Call again with confirm=true; you will be asked to approve.")

            env = config.env
            if allow_delete:
                approved_by = "settings"
                approvals.record(env, "disputes_delete", "approved", "settings", {"dispute_id": id})
            elif _can_ask_person(ctx):
                approvals.record(env, "disputes_delete", "requested", None, {"dispute_id": id})
                summary = "\n".join([
                    "Delete this dispute record? This cannot be undone.",
                    f"Against: {shown.party_name} ({shown.party_type})",
                    f"Status: {shown.status}",
                    f"Sent: {shown.sent_date or '(not set)'}",
                    f"Letter files on disk: {len(rec.get('letter_files', []))} (not deleted)",
                ])
                answer = await ctx.elicit(summary, DeleteApproval)
                if answer.action != "accept" or not answer.data.delete:
                    approvals.record(env, "disputes_delete", "declined", "person", {"dispute_id": id})
                    return DeleteResult(deleted=False, id=id, preview=shown,
                                        note="The person declined. Nothing was deleted.")
                approved_by = "person"
                approvals.record(env, "disputes_delete", "approved", "person", {"dispute_id": id})
            else:
                approvals.record(env, "disputes_delete", "refused", None,
                                 {"dispute_id": id, "reason": "approval_unavailable"})
                raise PrivacyOpsError(
                    "disputes", "approval_unavailable",
                    "this MCP client cannot ask you to approve a delete, and deletes are not pre-approved.",
                    "set PRIVACYOPS_DISPUTES_ALLOW_DELETE=true to allow deletes, or use a client that supports "
                    "approval prompts.",
                )

            def remove(data: dict) -> None:
                _get(data, id)
                del data["disputes"][id]

            store.update(remove)
            return DeleteResult(deleted=True, id=id, approved_by=approved_by, preview=shown)
