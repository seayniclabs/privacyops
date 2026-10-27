"""Skills, approval log, doctor, tool lock and security card: the trust surfaces.

Every test uses a temporary folder. Nothing reads or writes the real home folder.
"""

import asyncio
import json
import os
import pathlib
import socket
import stat
import subprocess
import sys

import pytest

from privacyops_mcp import doctor
from privacyops_mcp.common import DISCLAIMER
from privacyops_mcp.config import Config
from privacyops_mcp.server import build_server

ROOT = pathlib.Path(__file__).resolve().parent.parent
SKILLS = {"getting-started", "dispute-walkthrough"}


@pytest.fixture
def env(tmp_path):
    return {"PRIVACYOPS_DATA_DIR": str(tmp_path / "data"), "PRIVACYOPS_APPROVAL_LOG": str(tmp_path / "approvals.jsonl")}


def server(env, **kw):
    return build_server(Config(env=env, file_data={}), **kw)


def call(mcp, name, **args):
    _, structured = asyncio.run(mcp.call_tool(name, args))
    return structured


def read_log(path):
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


# --- skills ------------------------------------------------------------------------

def test_every_skill_is_an_mcp_prompt(env):
    prompts = {p.name for p in asyncio.run(server(env).list_prompts())}
    assert prompts == SKILLS


def test_prompt_text_matches_the_skill_file(env):
    for name in SKILLS:
        text = (ROOT / "skills" / name / "SKILL.md").read_text(encoding="utf-8")
        body = text.split("\n---\n", 1)[1]
        served = asyncio.run(server(env).get_prompt(name)).messages[0].content.text
        assert served == body


def test_skill_files_are_resources(env):
    uris = {str(r.uri) for r in asyncio.run(server(env).list_resources())}
    assert "skill://privacyops/getting-started/SKILL.md" in uris
    assert "skill://privacyops/dispute-walkthrough/SKILL.md" in uris


def test_every_skill_says_it_is_not_legal_advice(env):
    for name in SKILLS:
        text = asyncio.run(server(env).get_prompt(name)).messages[0].content.text
        assert "not legal advice" in text.lower()


def test_skills_never_tell_the_assistant_to_collect_an_ssn_or_account_number(env):
    import re
    for name in SKILLS:
        text = asyncio.run(server(env).get_prompt(name)).messages[0].content.text.lower()
        assert not re.search(r"(enter|provide|type|give|share|send)( your| the)? (social security|ssn|full account)", text)


def test_skill_checker_passes_and_catches_a_third_party_skill_without_a_license(tmp_path):
    ok = subprocess.run([sys.executable, str(ROOT / "scripts" / "check_skills.py")], capture_output=True, text=True)
    assert ok.returncode == 0, ok.stdout
    # A copy of the layout with a third-party skill that has no LICENSE file must fail.
    import shutil
    shutil.copytree(ROOT / "skills", tmp_path / "skills")
    shutil.copy(ROOT / "pyproject.toml", tmp_path / "pyproject.toml")
    shutil.copy(ROOT / "CREDITS.md", tmp_path / "CREDITS.md")
    (tmp_path / "scripts").mkdir()
    shutil.copy(ROOT / "scripts" / "check_skills.py", tmp_path / "scripts" / "check_skills.py")
    extra = tmp_path / "skills" / "borrowed"
    extra.mkdir()
    (extra / "SKILL.md").write_text("---\nname: borrowed\ndescription: x\nlicense: MIT\n"
                                    "source: https://example.org/other/borrowed\n---\n\nbody\n")
    bad = subprocess.run([sys.executable, str(tmp_path / "scripts" / "check_skills.py")], capture_output=True, text=True)
    assert bad.returncode == 1 and "borrowed" in bad.stdout


# --- discovery and promotion ---------------------------------------------------------

def test_discovery_lists_skills_and_names_the_publisher(env):
    out = call(server(env), "privacyops_modules")
    assert {s["name"] for s in out["skills"]} == SKILLS
    assert out["publisher"] == "Seaynic Labs"
    assert out["homepage"] == "https://github.com/seayniclabs/privacyops"
    assert out["disclaimer"] == DISCLAIMER


def test_no_promotion_reaches_the_model(env):
    srv = server(env)
    texts = [srv.instructions or ""] + [t.description or "" for t in asyncio.run(srv.list_tools())]
    texts += [asyncio.run(srv.get_prompt(p.name)).messages[0].content.text for p in asyncio.run(srv.list_prompts())]
    assert not any("seayniclabs.com" in x for x in texts)


def test_disclaimer_is_in_the_instructions(env):
    assert DISCLAIMER in (server(env).instructions or "")


# --- approval log ------------------------------------------------------------------------

def create(mcp, name="Card issuer", party="furnisher"):
    return call(mcp, "disputes_create", party_type=party, party_name=name,
                item_description="Balance is wrong, secret detail 4411.")


def test_settings_preapproval_is_logged_with_ids_only(env, tmp_path):
    mcp = server({**env, "PRIVACYOPS_DISPUTES_ALLOW_DELETE": "true"})
    d = create(mcp)
    call(mcp, "disputes_delete", id=d["id"], confirm=True)
    log = tmp_path / "approvals.jsonl"
    rows = read_log(log)
    assert [(r["decision"], r["approved_by"]) for r in rows] == [("approved", "settings")]
    assert rows[0]["dispute_id"] == d["id"] and rows[0]["tool"] == "disputes_delete"
    text = log.read_text()
    assert "Card issuer" not in text and "4411" not in text and "secret" not in text


def test_preview_is_not_logged(env, tmp_path):
    mcp = server(env)
    d = create(mcp)
    call(mcp, "disputes_delete", id=d["id"])
    assert not (tmp_path / "approvals.jsonl").exists()


def test_refusal_is_logged_when_the_client_cannot_ask(env, tmp_path):
    mcp = server(env)
    d = create(mcp)
    with pytest.raises(Exception) as err:
        call(mcp, "disputes_delete", id=d["id"], confirm=True)
    assert "approval_unavailable" in str(err.value)
    rows = read_log(tmp_path / "approvals.jsonl")
    assert [(r["decision"], r.get("reason")) for r in rows] == [("refused", "approval_unavailable")]


def _delete_through_client(env, answer):
    from mcp.shared.memory import create_connected_server_and_client_session
    from mcp.types import ElicitResult

    async def on_elicit(context, params):
        if answer is None:
            return ElicitResult(action="decline")
        return ElicitResult(action="accept", content={"delete": answer})

    async def run():
        async with create_connected_server_and_client_session(server(env), elicitation_callback=on_elicit) as client:
            made = await client.call_tool("disputes_create", {
                "party_type": "furnisher", "party_name": "Card issuer", "item_description": "Balance is wrong."})
            did = made.structuredContent["id"]
            result = await client.call_tool("disputes_delete", {"id": did, "confirm": True})
            return result.structuredContent, did

    return asyncio.run(run())


def test_person_grant_is_logged_as_requested_then_approved(env, tmp_path):
    out, did = _delete_through_client(env, True)
    assert out["deleted"] is True
    rows = read_log(tmp_path / "approvals.jsonl")
    assert [(r["decision"], r["approved_by"]) for r in rows] == [("requested", None), ("approved", "person")]
    assert all(r["dispute_id"] == did for r in rows)


def test_person_decline_is_logged(env, tmp_path):
    out, did = _delete_through_client(env, None)
    assert out["deleted"] is False
    rows = read_log(tmp_path / "approvals.jsonl")
    assert [(r["decision"], r["approved_by"]) for r in rows] == [("requested", None), ("declined", "person")]


def test_approval_log_is_owner_only(env, tmp_path):
    mcp = server({**env, "PRIVACYOPS_DISPUTES_ALLOW_DELETE": "true"})
    call(mcp, "disputes_delete", id=create(mcp)["id"], confirm=True)
    assert stat.S_IMODE((tmp_path / "approvals.jsonl").stat().st_mode) == 0o600


# --- doctor ------------------------------------------------------------------------------

def run_doctor(env_vars):
    return subprocess.run([sys.executable, "-m", "privacyops_mcp.server", "--doctor"],
                          env=env_vars, capture_output=True, text=True, timeout=60)


def test_doctor_on_an_empty_environment_reports_ready(tmp_path):
    env_vars = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(tmp_path)}
    r = run_doctor(env_vars)
    assert r.returncode == 0, r.stdout
    assert "ready" in r.stdout and "FIX" not in r.stdout


def test_doctor_exits_1_when_the_records_file_is_corrupt(tmp_path):
    data = tmp_path / "data"
    data.mkdir(mode=0o700)
    (data / "privacyops.json").write_text("{not json")
    env_vars = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(tmp_path),
                "PRIVACYOPS_DATA_DIR": str(data)}
    r = run_doctor(env_vars)
    assert r.returncode == 1 and "FIX" in r.stdout and "never overwrites" in r.stdout
    assert (data / "privacyops.json").read_text() == "{not json"


def test_doctor_flags_a_data_folder_other_users_can_read(env, tmp_path, capsys):
    mcp = server(env)
    create(mcp)
    os.chmod(tmp_path / "data", 0o755)
    assert doctor.run(Config(env=env, file_data={})) == 1
    assert "chmod 700" in capsys.readouterr().out


def test_doctor_flags_a_letter_file_that_a_record_names_but_is_missing(env, tmp_path, capsys):
    mcp = server(env)
    d = create(mcp)
    letter = call(mcp, "letters_generate", template="furnisher_dispute", item_description="Wrong.",
                  recipient_name="Card issuer", dispute_id=d["id"])
    os.remove(letter["path"])
    assert doctor.run(Config(env=env, file_data={})) == 1
    assert "listed but missing" in capsys.readouterr().out


def test_doctor_makes_no_network_calls(env, monkeypatch, capsys):
    def no_network(*a, **kw):
        raise AssertionError("doctor tried to use the network")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    assert doctor.run(Config(env=env, file_data={})) == 0


def test_package_imports_no_network_library():
    banned = ("import socket", "import urllib", "import http.client", "import httpx", "import requests",
              "import aiohttp", "import anthropic", "from urllib", "from http", "from httpx", "import ssl")
    for path in (ROOT / "src" / "privacyops_mcp").rglob("*.py"):
        text = path.read_text()
        for needle in banned:
            assert needle not in text, f"{path.name} imports {needle!r}"


# --- tool lock and security card ------------------------------------------------------

def test_tool_lock_is_current():
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "tool_lock.py"), "--check"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout


def test_security_card_is_current():
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "security_card.py"), "--check"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout
