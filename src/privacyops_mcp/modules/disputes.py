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

from ..common import clean, now_iso, parse_date, today
from ..config import Config
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

            if allow_delete:
                approved_by = "settings"
            elif _can_ask_person(ctx):
                summary = "\n".join([
                    "Delete this dispute record? This cannot be undone.",
                    f"Against: {shown.party_name} ({shown.party_type})",
                    f"Status: {shown.status}",
                    f"Sent: {shown.sent_date or '(not set)'}",
                    f"Letter files on disk: {len(rec.get('letter_files', []))} (not deleted)",
                ])
                answer = await ctx.elicit(summary, DeleteApproval)
                if answer.action != "accept" or not answer.data.delete:
                    return DeleteResult(deleted=False, id=id, preview=shown,
                                        note="The person declined. Nothing was deleted.")
                approved_by = "person"
            else:
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
