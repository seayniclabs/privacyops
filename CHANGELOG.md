# Changelog

PrivacyOps follows [semantic versioning](https://semver.org). Modules added after 0.1 ship switched off.

## 0.2.2 — 2026-10-27

**No code changes.** Change the pin to `privacyops-mcp==0.2.2`.

### Release process

- Built and published by GitHub Actions (`release.yml`) with PyPI trusted publishing. The wheel and sdist carry PyPI provenance and a GitHub build attestation; check a download with `gh attestation verify <file> --owner seayniclabs`.

## 0.2.1 — 2026-10-27

- Furnisher disputes now show the same 30-day due date in `disputes_get`, `disputes_list` and `disputes_update` as in `disputes_deadlines` (15 U.S.C. 1681s-2(a)(8)(E)(iii)); before, only `disputes_deadlines` showed it.

## 0.2.0 — 2026-10-27

- Skills: `getting-started` (setup, settings, `--doctor`, reading errors) and `dispute-walkthrough` (gathering facts, choosing the route and template, certified mail, deadlines, follow-up, when to get help). Each carries the not-legal-advice notice in plain words. No third-party skills.
- Every skill is also an MCP prompt, and each skill file an MCP resource (`skill://privacyops/<skill>/<file>`), so apps without Agent Skills support get them too.
- `disputes_deadlines` (read-only): every open dispute with its statutory response deadline, days remaining, an overdue flag and the next action. The periods come from 15 U.S.C. 1681i(a)(1) and 1681s-2(a)(8)(E)(iii) and (b)(2), checked against the official text on 2026-10-27; the tool names each fact it cannot know (the start of the clock, the 15-day extension, a furnisher's route) instead of guessing.
- Local approval log (`~/.local/state/privacyops/approvals.jsonl`, or `PRIVACYOPS_APPROVAL_LOG`): every delete asked, approved, declined or refused. Ids and decisions only; never names, item text, notes or letter text.
- `privacyops-mcp --doctor`: checks the data folder and its permissions, that the records file reads cleanly, that every letter a record names exists, and the approval log. Makes no network calls. Exits 1 when a `FIX` line appears.
- `tool-manifest.lock.json`: a hash of every tool description, prompt and the server instructions; CI fails if they change silently.
- README security card generated from the live server, `SECURITY.md`, `CREDITS.md`, five starter prompts, pinned install.
- Claude Code plugin manifest (`.claude-plugin/plugin.json`), with `.mcp.json` pinned to `privacyops-mcp==0.2.0`.
- Server reports its publisher and homepage in `privacyops_modules`.
- CI runs the skill checker, the tool lock check and the security card check.

## 0.1.0 — unreleased

- First release as one bundle with two modules: `disputes` (track disputes with consumer reporting agencies and furnishers) and `letters` (dispute letters from fixed templates).
- `disputes`: create, list (filtered and paged), get, update (status, sent date, note, with history), and delete. Delete asks you first, or is pre-approved with `PRIVACYOPS_DISPUTES_ALLOW_DELETE=true`.
- `letters`: two fixed templates (a reinvestigation request to a consumer reporting agency; a direct dispute to a furnisher), written as text files in your data folder. Your name, address, signature and any identifying numbers are placeholders you fill in by hand.
- Data is stored locally in one JSON file, written atomically so one update never drops other records. The file is created with owner-only permissions.
- No model or API calls. No Social Security number field exists anywhere.
- `privacyops_modules` discovery tool: which modules are on, what each tool does, where your data is, and the not-legal-advice disclaimer.
- Every generated letter carries the disclaimer in its footer. The templates have not been reviewed by a lawyer.
- Every tool returns structured data with a published output schema. Errors read `privacyops.<module>.<code>: <message> Fix: <hint>`.
- Runs over stdio or streamable HTTP. Starts with no settings.
