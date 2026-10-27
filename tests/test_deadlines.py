"""disputes_deadlines: statutory periods, overdue flags, next actions, and what the tool cannot know.

Dates are fixed with as_of, so the results do not depend on the day the tests run.
Sent date 2026-10-01: 30-day date 2026-10-31; 45-day date 2026-11-15 (agencies only).
"""

import asyncio
import pathlib

import pytest

from privacyops_mcp.config import Config
from privacyops_mcp.deadlines import BASE_DAYS, EXTENSION_DAYS, plan_for
from privacyops_mcp.server import build_server

ROOT = pathlib.Path(__file__).resolve().parent.parent


@pytest.fixture
def env(tmp_path):
    return {"PRIVACYOPS_DATA_DIR": str(tmp_path / "data"), "PRIVACYOPS_APPROVAL_LOG": str(tmp_path / "approvals.jsonl")}


def server(env):
    return build_server(Config(env=env, file_data={}))


def call(mcp, name, **args):
    _, structured = asyncio.run(mcp.call_tool(name, args))
    return structured


def sent(mcp, party_type="consumer_reporting_agency", name="Experian", sent_date="2026-10-01", status="sent"):
    return call(mcp, "disputes_create", party_type=party_type, party_name=name,
                item_description="An account listed as late that I paid on time.", status=status,
                sent_date=sent_date if status != "draft" else None)


def rows(mcp, as_of):
    return {r["party_name"]: r for r in call(mcp, "disputes_deadlines", as_of=as_of, limit=100)["disputes"]}


def test_agency_periods_are_30_and_45_days_from_the_sent_date():
    plan = plan_for("consumer_reporting_agency", __import__("datetime").date(2026, 10, 1))
    assert BASE_DAYS == 30 and EXTENSION_DAYS == 15
    assert plan.due.isoformat() == "2026-10-31" and plan.extended_due.isoformat() == "2026-11-15"
    assert plan.cite == "15 U.S.C. 1681i(a)(1)(A)"


def test_furnisher_has_a_30_day_date_and_no_extended_date():
    import datetime
    plan = plan_for("furnisher", datetime.date(2026, 10, 1))
    assert plan.due.isoformat() == "2026-10-31" and plan.extended_due is None
    assert "1681s-2(a)(8)(E)(iii)" in plan.cite and "1681s-2(b)(2)" in plan.cite


def test_days_remaining_before_the_deadline_and_no_overdue_flag(env):
    mcp = server(env)
    sent(mcp)
    row = rows(mcp, "2026-10-20")["Experian"]
    assert row["due_date"] == "2026-10-31" and row["days_remaining"] == 11
    assert row["overdue"] is False and "Wait for the response" in row["next_action"]


def test_past_30_days_within_45_is_flagged_and_explains_the_extension(env):
    mcp = server(env)
    sent(mcp)
    row = rows(mcp, "2026-11-05")["Experian"]
    assert row["overdue"] is True and row["days_remaining"] == -5
    assert "45-day date (2026-11-15)" in row["next_action"]
    assert "only if you sent relevant information in the first 30 days" in row["next_action"]


def test_past_45_days_says_past_the_deadline(env):
    mcp = server(env)
    sent(mcp)
    row = rows(mcp, "2026-11-20")["Experian"]
    assert row["overdue"] is True and row["next_action"].startswith("Past the deadline.")


def test_furnisher_past_30_days_has_no_extension_wording(env):
    mcp = server(env)
    sent(mcp, party_type="furnisher", name="Card issuer")
    row = rows(mcp, "2026-11-05")["Card issuer"]
    assert row["extended_due_date"] is None and row["overdue"] is True
    assert "45-day" not in row["next_action"]


def test_draft_has_no_deadline_and_says_to_send(env):
    mcp = server(env)
    sent(mcp, name="Equifax", status="draft")
    row = rows(mcp, "2026-10-20")["Equifax"]
    assert row["due_date"] is None and row["days_remaining"] is None and row["overdue"] is False
    assert row["next_action"].startswith("Send the letter")


def test_response_received_is_open_but_never_overdue(env):
    mcp = server(env)
    d = sent(mcp, name="TransUnion")
    call(mcp, "disputes_update", id=d["id"], status="response_received")
    row = rows(mcp, "2026-12-01")["TransUnion"]
    assert row["overdue"] is False and row["next_action"].startswith("Read the response")


def test_resolved_and_closed_disputes_are_not_listed(env):
    mcp = server(env)
    a = sent(mcp, name="Closed one")
    call(mcp, "disputes_update", id=a["id"], status="closed")
    b = sent(mcp, name="Resolved one")
    call(mcp, "disputes_update", id=b["id"], status="resolved")
    page = call(mcp, "disputes_deadlines", as_of="2026-10-20")
    assert page["open_total"] == 0 and page["disputes"] == []


def test_every_row_names_what_the_tool_cannot_know(env):
    mcp = server(env)
    sent(mcp)
    unknowns = rows(mcp, "2026-10-20")["Experian"]["unknowns"]
    assert any("receive" in u for u in unknowns)
    assert any("15 more days" in u and "1681i(a)(1)(B)" in u for u in unknowns)


def test_furnisher_unknowns_name_the_route_and_the_missing_extension(env):
    mcp = server(env)
    sent(mcp, party_type="furnisher", name="Card issuer")
    unknowns = rows(mcp, "2026-10-20")["Card issuer"]["unknowns"]
    assert any("Which route" in u for u in unknowns)
    assert any("does not say whether the 15-day extension" in u for u in unknowns)


def test_as_of_is_validated(env):
    mcp = server(env)
    with pytest.raises(Exception) as err:
        call(mcp, "disputes_deadlines", as_of="2026-02-30")
    assert "privacyops.disputes.bad_input" in str(err.value)


def test_rows_sort_by_due_date_and_page(env):
    mcp = server(env)
    sent(mcp, name="Late", sent_date="2026-10-10")
    sent(mcp, name="Early", sent_date="2026-10-01")
    draft = sent(mcp, name="Draft", status="draft")
    page = call(mcp, "disputes_deadlines", as_of="2026-10-20", limit=2)
    assert [r["party_name"] for r in page["disputes"]] == ["Early", "Late"]
    assert page["has_more"] is True and page["next_offset"] == 2 and page["open_total"] == 3
    last = call(mcp, "disputes_deadlines", as_of="2026-10-20", limit=2, offset=2)
    assert [r["id"] for r in last["disputes"]] == [draft["id"]]


def test_tool_description_and_output_cite_the_official_sources(env):
    mcp = server(env)
    tool = next(t for t in asyncio.run(mcp.list_tools()) if t.name == "disputes_deadlines")
    assert "https://www.law.cornell.edu/uscode/text/15/1681i" in tool.description
    assert "https://www.law.cornell.edu/uscode/text/15/1681s-2" in tool.description
    assert tool.annotations.readOnlyHint is True
    page = call(mcp, "disputes_deadlines", as_of="2026-10-20")
    assert {s["url"] for s in page["sources"]} == {
        "https://www.law.cornell.edu/uscode/text/15/1681i",
        "https://www.law.cornell.edu/uscode/text/15/1681s-2",
    }
    assert all(s["checked"] == "2026-10-27" for s in page["sources"])


def test_source_urls_are_recorded_in_the_code():
    text = (ROOT / "src" / "privacyops_mcp" / "deadlines.py").read_text()
    assert "https://www.law.cornell.edu/uscode/text/15/1681i" in text
    assert "https://www.law.cornell.edu/uscode/text/15/1681s-2" in text
