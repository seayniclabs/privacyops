# Security policy

## Reporting a vulnerability

Report it privately on GitHub: open the repository's **Security** tab and choose **Report a vulnerability**. Please don't open a public issue. Do not put dispute records, letter text or identity details in a report. Describe the problem and the steps to reproduce it with made-up data.

We acknowledge reports within 2 business days and aim to ship a fix for confirmed high-severity issues within 14 days. We credit reporters in the release notes unless you ask us not to.

## What PrivacyOps does and doesn't do

- It makes no network calls and has no telemetry. Only `--transport http` opens a listener, and it binds to `127.0.0.1` unless you change `--host`.
- It stores dispute records in one JSON file and letters as text files, both in the data folder (`~/.local/share/privacyops` by default), readable only by the owner. The files are not encrypted. Use full-disk encryption if the computer is shared.
- It has no tool that takes a password, an API key or a Social Security number, and it never asks for one.
- Deleting a dispute record needs the person's approval, given in their MCP app or ahead of time in settings. The assistant's own `confirm=true` is never enough.
- Every approval decision (asked, granted, declined, refused) is appended to a local log, `~/.local/state/privacyops/approvals.jsonl`. The log holds the tool name, a dispute id and the decision. It never holds names, item descriptions, reasons, notes or letter text.
- `tool-manifest.lock.json` records a hash of every tool description, prompt and the server instructions. CI fails if they change without the lock changing too.

## Supported versions

The latest minor release receives security fixes.
