---
name: qq-job-mail
description: Use when preparing or sending mail through a local Windows QQ or Foxmail account, including job applications, HTML mail, inline images, ordinary attachments, or delivery history.
---

# Codex QQ Mail Bridge

Use the single local tool installation at `__MAILER_ROOT__`. Invoke `run.ps1` with an absolute path. Read `__MAILER_ROOT__/使用说明.md` for setup and command details. This skill requires local Windows shell access and does not enable cloud chats or other computers.

## Account and state

Read the non-secret config to determine the configured sender. `account` identifies the QQ SMTP login and Windows credential entry; optional `sender` selects the same account's verified QQ/Foxmail alias for From, envelope sender and signatures. Do not invent an alias, switch credentials, create another database or run setup merely because sender differs from login. All conversations share this tool's configuration, SQLite history and previews.

If not configured, have the user run setup themselves in an interactive Windows terminal. Never ask for an authorization code in chat, read it yourself, print it, put it in arguments or files, or export credentials. A self-test must be submitted and the user must explicitly confirm actual receipt before confirm-test enables formal sending. Changing sender requires a fresh test: clear the enabled entry for this account and advance configured_epoch before testing; never alter attempts or fabricate receipt confirmation.

## Drafts

For job applications, prepare a UTF-8 CSV/XLSX with 单位,岗位,性质,邮箱 and optional 联系人,简历路径,主题. 性质 is 高校/研究所/企业. Use verified facts and recipient addresses; never invent qualifications. Run `run.ps1 prepare ABSOLUTE_TABLE_PATH`.

For general mail, write UTF-8 JSON with `to`, `subject`, `body`; optional `html`, `attachments` (file paths), `inline_images` (objects with `path` and unique `cid`). Reference images as `<img src="cid:CID">`. Run `run.ps1 prepare-mail ABSOLUTE_JSON_PATH`. Use absolute file paths across projects. Total source files must be at most 15 MiB. One recipient only; no CC/BCC. Never force general mail into a job template.

Read the actual saved draft with `run.ps1 preview ID`. Show the sender, recipient, complete subject/body, HTML content when present, and all inline/attached file paths and hashes before sending. Source files are hash checked; regenerate and review if changed.

## Sending

Require explicit authorization for each specific email. Creating/installing this skill or preparing a table is not sending authorization. After approval invoke `run.ps1 send ID` in an interactive terminal; enter the exact confirmation phrase only for the authorized draft. If the user explicitly asked for a single test email and delegated its content and test attachments, that authorizes that one test; show what will be sent and proceed without another approval. Do not bypass review_send, call deliver directly, add auto-confirm switches, or loop over recipients.

Preserve the 60-second interval and duplicate protection. Report SMTP acceptance as submitted, not received. For uncertain results or interrupted sends, do not automatically retry or unlock records; resolve only after explicit user instruction and investigation. `run.ps1 records` exports history locally; never publish it.
