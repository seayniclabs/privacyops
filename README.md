# PrivacyOps

<!-- mcp-name: io.github.seayniclabs/privacyops -->

PrivacyOps is an MCP server for consumers who are tracking credit-bureau disputes. It keeps a record of each dispute on your own computer, and it writes dispute letters from fixed templates that you fill in by hand.

> **Not legal advice.** PrivacyOps is a tracking and drafting aid. It does not know your facts or the law in your state. **The letter templates have not been reviewed by a lawyer.** For legal questions, ask a lawyer or a consumer-protection agency.

It is a **bundle**: one server made of modules. You switch on the modules you use. New modules arrive switched off, so an update never changes what your assistant can do until you choose to.

| Module | What it does | Status |
|---|---|---|
| `disputes` | Track disputes with consumer reporting agencies (Equifax, Experian, TransUnion) and with furnishers (the companies that report to them): status, sent date, the 30-day reinvestigation due date, and a history of changes | 0.1 |
| `letters` | Dispute letters from two fixed templates, saved as text files on your computer | 0.1 |

Planned, not built: data-broker opt-outs and credit-freeze tools. These are ideas, not commitments.

**Audience:** consumers who want to keep their own record of disputes and write clear letters. PrivacyOps is not for lawyers, credit repair businesses, or anyone handling other people's identity information.

## What stays on your computer

- Dispute records are kept in one JSON file in your data folder. Default: `~/.local/share/privacyops/privacyops.json`. Set `PRIVACYOPS_DATA_DIR` to choose another folder.
- Letters are saved as Markdown text files in `letters/` inside that folder.
- Nothing is sent to Seaynic Labs or to any other service. PrivacyOps makes no network calls.
- The files are created readable only by you (mode `0600`), but they are **not encrypted**. Anyone with access to your account can read them. Keep the folder out of shared or synced folders you do not control.
- Your AI assistant can see what you type into the chat, and so can the company that runs it. PrivacyOps cannot change that.

**PrivacyOps never asks for a Social Security number.** If a bureau asks for identifying numbers, you write them in by hand on the printed letter.

## Install

PrivacyOps needs Python 3.11 or newer. With [uv](https://docs.astral.sh/uv/) you do not install anything ahead of time:

```bash
uvx privacyops-mcp --version
```

Or with pip:

```bash
pip install privacyops-mcp
```

Uninstalling with `pip uninstall privacyops-mcp` removes the program only. **Your records and letters stay in the data folder.** Delete that folder yourself if you want them gone.

## Settings

PrivacyOps starts without any settings. The defaults are safe.

| Variable | Module | What it does |
|---|---|---|
| `PRIVACYOPS_DATA_DIR` | all | Folder for your records and letters. Default `~/.local/share/privacyops` |
| `PRIVACYOPS_DISPUTES_ALLOW_DELETE` | disputes | `false` by default: you approve each delete. `true` lets the assistant delete a dispute record without asking. |
| `PRIVACYOPS_<MODULE>_ENABLED` | any | `false` turns a module off, e.g. `PRIVACYOPS_LETTERS_ENABLED=false` |

**Config file (optional).** PrivacyOps also reads `~/.config/privacyops/config.toml`, or the file named by `PRIVACYOPS_CONFIG`. Environment variables win over the file.

```toml
data_dir = "/Users/you/Documents/privacyops"

[disputes]
allow_delete = false

[letters]
enabled = true
```

## Add it to your MCP client

Most clients use the same JSON shape. Put it where your client keeps MCP servers:

```json
{
  "mcpServers": {
    "privacyops": {
      "command": "uvx",
      "args": ["privacyops-mcp"],
      "env": {
        "PRIVACYOPS_DATA_DIR": "/Users/you/Documents/privacyops"
      }
    }
  }
}
```

| Client | Where the config goes |
|---|---|
| Claude Desktop | `claude_desktop_config.json` (Settings → Developer → Edit Config) |
| Claude Code | `claude mcp add privacyops -- uvx privacyops-mcp`, or a project `.mcp.json` |
| Cursor | `~/.cursor/mcp.json`, or `.cursor/mcp.json` in a project |
| VS Code | `.vscode/mcp.json`, using `"servers"` instead of `"mcpServers"` |
| Sonique, Hermes, OpenClaw, others | Any client that launches a stdio MCP server: command `uvx`, args `["privacyops-mcp"]`, plus the env values |

**Over HTTP.** For clients that connect to a URL instead of launching a process:

```bash
privacyops-mcp --transport http --port 8765
```

It serves streamable HTTP at `http://127.0.0.1:8765/mcp` and listens only on your own machine by default. Put authentication in front of it before exposing it anywhere else.

## Tools

| Tool | What it returns |
|---|---|
| `privacyops_modules` | Which modules are on, what each tool does, where your data is, and the disclaimer. Call this first. |
| `disputes_list` | Dispute summaries, filtered by status or party type, paged with `offset` |
| `disputes_get` | One dispute with its details, due date, letters written, and history |
| `disputes_create` | Starts tracking a dispute |
| `disputes_update` | Changes status, sets the sent date, or adds a note. Every change goes into the history. |
| `disputes_delete` | Deletes a dispute record. Preview first; you approve it. Letter files are not deleted. |
| `letters_templates` | The templates, the agencies with checked contact details, and the disclaimer |
| `letters_generate` | Writes a letter to a text file. Attaches it to a dispute if you give its id. |

Every tool returns structured data with a published schema. Errors read `privacyops.<module>.<code>: <message> Fix: <hint>`.

## Letter templates and sources

Both templates are fixed text. Nothing is generated by a model. Each citation was checked against the official statute text on 2026-10-27.

| Template | Used for | Cites (15 U.S.C.) | Source |
|---|---|---|---|
| `cra_dispute` | Asking a consumer reporting agency to reinvestigate an item | 1681i(a)(1)(A), (a)(5)(A), (a)(6)(A), (a)(7) | https://www.law.cornell.edu/uscode/text/15/1681i |
| `furnisher_dispute` | Disputing directly with the company that reported the item | 1681s-2(a)(8), (a)(8)(D), (a)(8)(E) | https://www.law.cornell.edu/uscode/text/15/1681s-2 |

**Contact details** are included only where the agency's own site was checked on 2026-10-27:

| Agency | Mailing address in letters | Online disputes | Checked |
|---|---|---|---|
| Equifax | Not published on the official page: fill in by hand | https://www.equifax.com/personal/credit-report-services/credit-dispute/ | 2026-10-27 |
| Experian | Experian, Dispute by Mail, P.O. Box 4500, Allen, TX 75013 | https://www.experian.com/disputes/main.html (sign-in required) | 2026-10-27 |
| TransUnion | **Not verified** (the official page returned an error when checked): fill in by hand | Not verified: fill in by hand | not checked |

Check any address against the agency's own website before you mail a letter. Agencies change their addresses.

## Safety

- PrivacyOps makes no network calls and sends nothing anywhere.
- Deleting a dispute record asks you first, through your MCP client's approval prompt. The assistant cannot approve on your behalf. Some clients cannot show approval prompts. In those, deletes are refused unless you set `PRIVACYOPS_DISPUTES_ALLOW_DELETE=true`.
- Writes never delete other records. A failed save leaves the previous file unchanged, and an unreadable file is never overwritten.
- The disclaimer appears in the server's instructions, in `privacyops_modules`, and in every letter's footer.

## Develop

```bash
uv venv -p 3.11 && uv pip install -e '.[dev]'
.venv/bin/pytest
```

The tests use temporary data folders and make no network calls.

## License

MIT. Published by Seaynic Labs.
