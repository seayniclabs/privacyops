---
name: getting-started
description: Set up and check the PrivacyOps MCP bundle, which tracks credit-report disputes and drafts dispute letters on this computer. Use when the user installs PrivacyOps, asks what it does, gets an error that starts with "privacyops.", wants to find where their records are, or wants to switch a module on or off.
license: MIT
source: https://github.com/seayniclabs/privacyops
author: Seaynic Labs
---

# Getting started with PrivacyOps

**This is not legal advice.** PrivacyOps keeps a record of disputes and fills in letter templates. It does not know the user's facts or their state's law, and no lawyer has reviewed the templates. For legal questions, the user should ask a lawyer or a consumer-protection agency.

PrivacyOps makes no network calls. It keeps records in a folder on this computer. It never asks for a Social Security number, and you must not ask the user to type one into the chat.

## 1. See what is on

Call `privacyops_modules` first. It returns the modules that are on, the tools in each one, the `data_dir` where records are kept, and the skills. Tell the user the `data_dir` value.

Two modules ship, and both are on by default:

- `disputes`: records, deadlines and delete
- `letters`: the templates and the letter files

To turn a module off, the user adds `PRIVACYOPS_<MODULE>_ENABLED=false` to the MCP app's `env` block (for example `PRIVACYOPS_LETTERS_ENABLED=false`) and restarts the app.

## 2. Settings the user can add

No setting is required. PrivacyOps starts with none.

| Setting | Effect |
|---|---|
| `PRIVACYOPS_DATA_DIR` | Folder for records and letters. Default `~/.local/share/privacyops`. |
| `PRIVACYOPS_DISPUTES_ALLOW_DELETE` | `true` lets the assistant delete a record without asking. Default: each delete needs the user's approval. Never set this for the user. |
| `PRIVACYOPS_APPROVAL_LOG` | Path of the approval log. Default `~/.local/state/privacyops/approvals.jsonl`. |

Settings go in the MCP app's `env` block. The user can also put them in `~/.config/privacyops/config.toml`; environment variables win over that file.

## 3. Check the setup

The user runs this in a terminal:

```bash
uvx privacyops-mcp --doctor
```

Doctor checks the data folder and its permissions, whether the records file reads cleanly, whether every letter a record names exists, and the approval log. It prints `ok` or `FIX` for each item, and exits 1 when a `FIX` line appears. Pass each `FIX` line to the user as written. Doctor changes nothing.

## 4. First use

1. Call `disputes_create` with `status` set to `draft`. Keep the `id` from the reply.
2. Call `letters_templates` to see the two templates and which agencies have a checked mailing address.
3. Call `letters_generate` with the template, the item, the reason, and `dispute_id`. The letter is saved as a text file and attached to the record.
4. Tell the user to fill in these placeholders by hand on the printed letter: `[YOUR FULL NAME]`, `[YOUR ADDRESS]`, `[YOUR SIGNATURE]`, and the enclosure line. The placeholders stay in the file on purpose.

The `dispute-walkthrough` skill covers the full process, from gathering facts to following up.

## 5. Check deadlines

Call `disputes_deadlines`. It lists every open dispute with the statutory response deadline, the days remaining, an `overdue` flag, and a `next_action`. Each row also has `unknowns`: facts the tool cannot know. Read those to the user exactly as written. The tool never guesses at them.

## 6. Deletes

`disputes_delete` returns a preview unless `confirm` is `true`. With `confirm=true`, the user's MCP app shows an approval prompt, and only the user can answer it. You cannot answer it for them.

If the app cannot show prompts, the tool returns `disputes.approval_unavailable`. Explain the two ways forward: use an app that shows approval prompts, or have the user set `PRIVACYOPS_DISPUTES_ALLOW_DELETE=true` themselves.

A delete does not remove letter files. Tell the user where they are: the `letters` folder inside `data_dir`.

Every approval decision (asked, granted, declined or refused) adds one line to the approval log. Each line holds the tool name, the dispute id and the decision. It never holds names or text.

## 7. Read the errors

Every error reads `privacyops.<module>.<code>: <message> Fix: <hint>`. Pass the `Fix:` text to the user as written.

| Code | What to do |
|---|---|
| `storage.corrupt_store` | The records file cannot be read, and nothing was changed. Ask the user to move the file aside and restore a backup. Never write over it. |
| `storage.unwritable` | The data folder cannot be created. Fix `PRIVACYOPS_DATA_DIR`. |
| `storage.write_failed` | The save failed and the previous file is unchanged. Check disk space and folder permissions. |
| `disputes.not_found` | No record has that id. Call `disputes_list` to find it. |
| `disputes.approval_unavailable` | The app cannot show approval prompts. See section 6. |
| `disputes.bad_input`, `letters.bad_input` | A value is wrong. The message names the field. |

Uninstalling with `pip uninstall privacyops-mcp` removes the program only. Records and letters stay in `data_dir` until the user deletes that folder.
