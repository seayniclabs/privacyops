"""Start-and-list, module switches, disputes and letters, data safety, delete approval.

Every test uses a temporary data folder. Nothing reads or writes the real home folder, and nothing
touches the network.
"""

import asyncio
import json
import os
import re
import stat
import sys
import threading

import pytest

from privacyops_mcp import __version__
from privacyops_mcp.common import DISCLAIMER
from privacyops_mcp.config import Config
from privacyops_mcp.server import build_server
from privacyops_mcp.store import Store
from privacyops_mcp.templates import TEMPLATES

ALL = {
    "privacyops_modules",
    "disputes_list", "disputes_get", "disputes_create", "disputes_update", "disputes_delete", "disputes_deadlines",
    "letters_templates", "letters_generate",
}


@pytest.fixture
def data_dir(tmp_path):
    return tmp_path / "data"


@pytest.fixture
def env(data_dir):
    # The approval log goes into the temporary folder too, never into the real home folder.
    return {"PRIVACYOPS_DATA_DIR": str(data_dir), "PRIVACYOPS_APPROVAL_LOG": str(data_dir.parent / "approvals.jsonl")}


def server(env, **kw):
    return build_server(Config(env=env, file_data={}), **kw)


def tools(mcp):
    return {t.name for t in asyncio.run(mcp.list_tools())}


def call(mcp, name, **args):
    """Return the structured result, or raise the tool's error."""
    _, structured = asyncio.run(mcp.call_tool(name, args))
    return structured


def create(mcp, **over):
    args = {"party_type": "consumer_reporting_agency", "party_name": "Experian",
            "item_description": "An account listed as late that I paid on time."}
    args.update(over)
    return call(mcp, "disputes_create", **args)


# --- start, list, switches, config --------------------------------------------

def test_empty_env_starts_and_lists_every_tool(env):
    assert tools(server(env)) == ALL


def test_every_tool_has_an_output_schema(env):
    assert all(t.outputSchema for t in asyncio.run(server(env).list_tools()))


def test_no_ssn_field_in_any_schema(env):
    blob = json.dumps([t.model_dump() for t in asyncio.run(server(env).list_tools())])
    assert not re.search(r"ssn|social.?security|tax.?id", blob, re.I)


def test_letters_module_switch_off_hides_its_tools(env):
    names = tools(server({**env, "PRIVACYOPS_LETTERS_ENABLED": "false"}))
    assert not any(n.startswith("letters_") for n in names)
    assert "disputes_list" in names


def test_config_file_is_read_and_env_wins(tmp_path):
    cfg = Config(env={"PRIVACYOPS_DATA_DIR": str(tmp_path / "env")},
                 file_data={"data_dir": str(tmp_path / "file"),
                            "disputes": {"allow_delete": True}, "letters": {"enabled": False}})
    assert cfg.data_dir() == tmp_path / "env"
    assert cfg.flag("disputes", "allow_delete", False) is True
    assert cfg.enabled("letters", True) is False


def test_discovery_reports_disclaimer_and_settings(env):
    out = call(server(env), "privacyops_modules")
    assert out["disclaimer"] == DISCLAIMER
    assert out["data_dir"] == env["PRIVACYOPS_DATA_DIR"]
    detail = call(server(env), "privacyops_modules", module="disputes")
    assert detail["modules"][0]["settings"][0]["env_var"] == "PRIVACYOPS_DISPUTES_ALLOW_DELETE"


def test_missing_data_folder_is_created_only_on_first_write(env, data_dir):
    mcp = server(env)
    assert not data_dir.exists()
    assert call(mcp, "disputes_list")["total"] == 0
    assert not data_dir.exists()
    create(mcp)
    assert (data_dir / "privacyops.json").is_file()


# --- disputes: no data loss ----------------------------------------------------

def test_create_update_list_keeps_other_records(env, data_dir):
    mcp = server(env)
    a = create(mcp, party_name="Experian")
    b = create(mcp, party_name="TransUnion")
    c = create(mcp, party_type="furnisher", party_name="Card issuer")
    call(mcp, "disputes_update", id=b["id"], status="sent", sent_date="2026-10-01")

    rows = {r["id"]: r for r in call(mcp, "disputes_list", limit=10)["disputes"]}
    assert rows[a["id"]]["status"] == "draft"
    assert rows[b["id"]]["status"] == "sent" and rows[b["id"]]["sent_date"] == "2026-10-01"
    assert rows[c["id"]]["status"] == "draft"
    assert call(mcp, "disputes_get", id=a["id"])["history"][0]["action"] == "created"


def test_update_never_drops_unrelated_top_level_data(env, data_dir):
    mcp = server(env)
    a = create(mcp)
    path = data_dir / "privacyops.json"
    data = json.loads(path.read_text())
    data["future_section"] = {"keep": "me"}
    path.write_text(json.dumps(data))
    call(mcp, "disputes_update", id=a["id"], note="checked the report")
    assert json.loads(path.read_text())["future_section"] == {"keep": "me"}


def test_double_update_from_two_writers_keeps_both(env, data_dir):
    first, second = Store(data_dir), Store(data_dir)
    mcp = server(env)
    a = create(mcp, party_name="Experian")
    b = create(mcp, party_name="Equifax")
    first.update(lambda d: d["disputes"][a["id"]].__setitem__("status", "sent"))
    second.update(lambda d: d["disputes"][b["id"]].__setitem__("status", "resolved"))
    rows = second.read()["disputes"]
    assert rows[a["id"]]["status"] == "sent"
    assert rows[b["id"]]["status"] == "resolved"


def test_threaded_writers_lose_nothing(data_dir):
    store = Store(data_dir)

    def add(n):
        def fn(d):
            d["disputes"][f"t{n:03d}"] = {"id": f"t{n:03d}"}
        store.update(fn)

    threads = [threading.Thread(target=add, args=(n,)) for n in range(40)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(store.read()["disputes"]) == 40


def test_paging_returns_next_offset(env):
    mcp = server(env)
    for i in range(5):
        create(mcp, party_name=f"Company {i}")
    first = call(mcp, "disputes_list", limit=2)
    assert len(first["disputes"]) == 2 and first["total"] == 5 and first["has_more"] is True
    last = call(mcp, "disputes_list", limit=2, offset=first["next_offset"] * 2)
    assert last["has_more"] is False and last["next_offset"] is None


def test_due_date_for_agency_and_furnisher_disputes(env):
    mcp = server(env)
    agency = create(mcp, sent_date="2026-10-01")
    furnisher = create(mcp, party_type="furnisher", sent_date="2026-10-01")
    assert agency["due_date"] == "2026-10-31"
    assert "1681i(a)(1)(A)" in agency["due_note"]
    # matches disputes_deadlines: 30 days, 15 U.S.C. 1681s-2(a)(8)(E)(iii)
    assert furnisher["due_date"] == "2026-10-31" and "1681s-2(a)(8)(E)(iii)" in furnisher["due_note"]
    assert create(mcp, party_type="furnisher")["due_date"] is None  # no sent date, no due date


def test_sent_status_without_date_uses_today(env):
    out = create(server(env), status="sent")
    assert out["sent_date"] is not None


def test_status_changes_are_recorded_in_history(env):
    mcp = server(env)
    a = create(mcp)
    call(mcp, "disputes_update", id=a["id"], status="response_received")
    call(mcp, "disputes_update", id=a["id"], status="response_received")  # no change, no entry
    history = call(mcp, "disputes_get", id=a["id"])["history"]
    assert [h["action"] for h in history] == ["created", "status"]
    assert history[1]["from_status"] == "draft" and history[1]["to_status"] == "response_received"


def test_bad_input_is_named(env):
    mcp = server(env)
    with pytest.raises(Exception) as err:
        create(mcp, sent_date="2026-02-30")
    assert "privacyops.disputes.bad_input" in str(err.value)
    with pytest.raises(Exception) as err:
        call(mcp, "disputes_update", id="nope", status="sent")
    assert "privacyops.disputes.not_found" in str(err.value)


def test_corrupt_store_is_reported_and_never_overwritten(env, data_dir):
    mcp = server(env)
    data_dir.mkdir(parents=True)
    path = data_dir / "privacyops.json"
    path.write_text("{not json")
    with pytest.raises(Exception) as err:
        create(mcp)
    assert "privacyops.storage.corrupt_store" in str(err.value)
    assert path.read_text() == "{not json"


def test_failed_write_leaves_previous_data_intact(env, data_dir, monkeypatch):
    mcp = server(env)
    a = create(mcp, party_name="Experian")
    before = (data_dir / "privacyops.json").read_bytes()

    def boom(src, dst):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr("privacyops_mcp.store.os.replace", boom)
    with pytest.raises(Exception) as err:
        create(mcp, party_name="Equifax")
    assert "privacyops.storage.write_failed" in str(err.value)
    assert (data_dir / "privacyops.json").read_bytes() == before
    assert not [p for p in data_dir.iterdir() if p.name.endswith(".tmp")]
    assert call(mcp, "disputes_get", id=a["id"])["party_name"] == "Experian"


def test_data_file_is_private(env, data_dir):
    create(server(env))
    assert stat.S_IMODE((data_dir / "privacyops.json").stat().st_mode) == 0o600


# --- letters ---------------------------------------------------------------------

def test_letter_has_disclaimer_placeholders_and_private_file(env, data_dir):
    out = call(server(env), "letters_generate", template="cra_dispute",
               item_description="Account listed as late in March 2026.", agency_key="experian")
    text = out["text"]
    assert DISCLAIMER in text
    assert "have not been reviewed by a lawyer" in text
    for placeholder in ("[YOUR FULL NAME]", "[YOUR ADDRESS]", "[YOUR SIGNATURE]"):
        assert placeholder in text
    assert "P.O. Box 4500" in text and "Allen, TX 75013" in text
    assert "15 U.S.C. 1681i(a)(1)(A)" in text
    path = data_dir / "letters" / os.path.basename(out["path"])
    assert path.read_text() == text
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_letter_for_agency_without_checked_address_leaves_placeholder(env):
    out = call(server(env), "letters_generate", template="cra_dispute",
               item_description="Wrong address.", agency_key="transunion")
    assert "[RECIPIENT MAILING ADDRESS: fill in from the company's own website]" in out["text"]
    assert out["recipient"]["address"] is None
    out = call(server(env), "letters_generate", template="cra_dispute",
               item_description="Wrong address.", agency_key="equifax")
    assert out["recipient"]["address"] is None


def test_furnisher_letter_attaches_to_dispute(env):
    mcp = server(env)
    d = create(mcp, party_type="furnisher", party_name="Card issuer")
    out = call(mcp, "letters_generate", template="furnisher_dispute", item_description="Balance is wrong.",
               recipient_name="Card issuer", dispute_id=d["id"], reason="I paid it in full.")
    assert out["dispute_id"] == d["id"]
    assert "1681s-2(a)(8)" in out["text"] and "I paid it in full." in out["text"]
    record = call(mcp, "disputes_get", id=d["id"])
    assert record["letter_files"] == [os.path.basename(out["path"])]
    assert record["history"][-1]["action"] == "letter"


def test_letter_text_is_literal_not_template_code(env):
    out = call(server(env), "letters_generate", template="cra_dispute",
               item_description="Shows {reason} and {0} and <b>tags</b> & ampersands.",
               agency_key="experian")
    assert "Shows {reason} and {0} and <b>tags</b> & ampersands." in out["text"]


def test_unknown_agency_and_dispute_are_named(env):
    mcp = server(env)
    with pytest.raises(Exception) as err:
        call(mcp, "letters_generate", template="cra_dispute", item_description="x", agency_key="nowhere")
    assert "privacyops.letters.bad_input" in str(err.value)
    with pytest.raises(Exception) as err:
        call(mcp, "letters_generate", template="cra_dispute", item_description="x", agency_key="experian",
             dispute_id="missing")
    assert "privacyops.disputes.not_found" in str(err.value)


def test_templates_list_only_checked_contact_details(env):
    out = call(server(env), "letters_templates")
    by_key = {a["key"]: a for a in out["agencies"]}
    assert by_key["experian"]["source_checked"] == "2026-10-27"
    assert by_key["equifax"]["mail_address"] is None
    assert by_key["transunion"]["source_url"] is None and by_key["transunion"]["mail_address"] is None
    assert {t["id"] for t in out["templates"]} == set(TEMPLATES)


def test_every_template_cites_official_source():
    for t in TEMPLATES.values():
        assert t.sources and all(s.startswith("https://www.law.cornell.edu/uscode/text/15/") for s in t.sources)
        assert t.cites


# --- delete approval ---------------------------------------------------------------

def test_delete_without_confirm_only_previews(env):
    mcp = server(env)
    a = create(mcp)
    out = call(mcp, "disputes_delete", id=a["id"])
    assert out["deleted"] is False and out["preview"]["id"] == a["id"]
    assert call(mcp, "disputes_get", id=a["id"])["id"] == a["id"]


def test_confirm_alone_cannot_delete_without_a_person_or_setting(env):
    mcp = server(env)
    a = create(mcp)
    with pytest.raises(Exception) as err:
        call(mcp, "disputes_delete", id=a["id"], confirm=True)
    assert "privacyops.disputes.approval_unavailable" in str(err.value)
    assert call(mcp, "disputes_get", id=a["id"])["id"] == a["id"]


def test_setting_preapproves_delete(env):
    mcp = server({**env, "PRIVACYOPS_DISPUTES_ALLOW_DELETE": "true"})
    a = create(mcp)
    out = call(mcp, "disputes_delete", id=a["id"], confirm=True)
    assert out["deleted"] is True and out["approved_by"] == "settings"
    with pytest.raises(Exception):
        call(mcp, "disputes_get", id=a["id"])


def _session_delete(env, answer):
    """Create a dispute and delete it through a real client that answers the approval prompt."""
    from mcp.shared.memory import create_connected_server_and_client_session
    from mcp.types import ElicitResult

    asked = []

    async def on_elicit(context, params):
        asked.append(params.message)
        if answer is None:
            return ElicitResult(action="decline")
        return ElicitResult(action="accept", content={"delete": answer})

    async def run():
        async with create_connected_server_and_client_session(server(env), elicitation_callback=on_elicit) as client:
            made = await client.call_tool("disputes_create", {
                "party_type": "furnisher", "party_name": "Card issuer",
                "item_description": "Balance is wrong."})
            did = made.structuredContent["id"]
            result = await client.call_tool("disputes_delete", {"id": did, "confirm": True})
            return result.structuredContent, did

    out, did = asyncio.run(run())
    return out, did, asked


def test_person_approves_delete_through_the_client(env, data_dir):
    out, did, asked = _session_delete(env, True)
    assert out["deleted"] is True and out["approved_by"] == "person"
    assert "Card issuer" in asked[0] and "cannot be undone" in asked[0]
    assert did not in Store(data_dir).read()["disputes"]


def test_person_declines_delete_through_the_client(env, data_dir):
    out, did, _ = _session_delete(env, None)
    assert out["deleted"] is False
    assert did in Store(data_dir).read()["disputes"]


# --- real stdio start with an empty environment ----------------------------------

def test_stdio_start_with_empty_env_reports_version_and_tools(tmp_path):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(tmp_path)}
    params = StdioServerParameters(command=sys.executable, args=["-m", "privacyops_mcp.server"], env=env)

    async def run():
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                init = await session.initialize()
                listed = await session.list_tools()
                return init.serverInfo.version, {t.name for t in listed.tools}

    version, names = asyncio.run(run())
    assert version == __version__
    assert names == ALL
