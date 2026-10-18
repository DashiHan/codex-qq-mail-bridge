# Codex QQ Mail Bridge

**Connect Codex to QQ Mail and Foxmail through a reusable Windows personal skill.**

[中文说明](README.zh-CN.md) · [Command reference](docs/USAGE.md) · [Privacy](docs/PRIVACY.md)

Send mail directly through QQ SMTP over verified TLS, with frozen drafts, per-message review, inline images, attachments and shared delivery history. Browser automation is not required. This is a community project, not an official Tencent or OpenAI integration.

## Read your inbox

Read-only IMAP uses the existing Windows credential. Enable IMAP in QQ Mail if needed. No mailbox flags are changed.

```powershell
.\qq_job_mailer\run.ps1 inbox --limit 20
.\qq_job_mailer\run.ps1 inbox --unread
.\qq_job_mailer\run.ps1 search --subject "interview" --since 2026-01-01
.\qq_job_mailer\run.ps1 read MAIL_REFERENCE
.\qq_job_mailer\run.ps1 attachments MAIL_REFERENCE
.\qq_job_mailer\run.ps1 download MAIL_REFERENCE 1 --output .\private\downloads
.\qq_job_mailer\run.ps1 reply MAIL_REFERENCE --body-file .\private\reply.txt
```

Use the exact mailbox-version:UID reference from inbox/search, not its row number. Keyword searches scan at most500 recent messages after date/unread filtering; results disclose incomplete scans. Messages up to25 MiB can be read. Downloaded files are never automatically opened. Reply only creates a local draft and still requires review and `send DRAFT_ID`. Email contents, downloads and replies must remain private.

## Features

- QQ SMTP login with an authorization code held in Windows Credential Manager.
- Separate login account and outward sender for a same-account Foxmail alias.
- Chinese and English subjects, plain text and HTML bodies, CID inline images, ordinary file attachments.
- Job application templates for universities, research institutes and companies; CSV and optional XLSX import.
- Local previews, attachment hashes, SQLite duplicate protection and a minimum 60-second interval.
- Self-test receipt confirmation before formal sending; no unattended bulk sending or automatic retries.
- A personal Codex skill shared across local projects through one fixed tool directory.

## Requirements

Windows, PowerShell, Python 3.10+, a QQ Mail account with SMTP and, for reading, IMAP enabled and an authorization code, and network access to `smtp.qq.com:465` and, for reading, `imap.qq.com:993`. CSV/general email require only the Python standard library. XLSX optionally requires `openpyxl`.

## Install

Clone or download this repository to a stable directory. Open PowerShell in the checkout:

```powershell
py -3 -m venv .\qq_job_mailer\.venv
# Optional, only for XLSX import:
.\qq_job_mailer\.venv\Scripts\python.exe -m pip install -r .\requirements-optional.txt
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install.ps1
```

The installer registers `qq-job-mail` in `$CODEX_HOME/skills`, or `~/.codex/skills` when unset, and resolves the current checkout path. It does not configure an account or send mail. Keep this checkout in place; moving it requires reviewing/reinstalling the skill. A differing existing skill is preserved and reported, never silently overwritten. Open a new local Codex conversation; restart Codex if discovery has not refreshed.

## Configure and verify

Run setup yourself in an interactive terminal; never paste the authorization code into a chat:

```powershell
.\qq_job_mailer\run.ps1 doctor
.\qq_job_mailer\run.ps1 setup
```

For a same-account Foxmail alias, add `"sender": "sender@foxmail.com"` to the generated local `qq_job_mailer/config.json` **before the first test**, keeping `account` unchanged. Use your actual alias. Setup again rebuilds the configuration. Changing sender after enabling delivery requires a fresh test and receipt confirmation; see [usage](docs/USAGE.md).

```powershell
.\qq_job_mailer\run.ps1 test
# Check the actual received message, then:
.\qq_job_mailer\run.ps1 confirm-test
```

The terminal displays each exact confirmation phrase. Formal sending is enabled only after you report receiving the submitted self-test. SMTP acceptance means **submitted**, not delivered or read.

## Use in Codex

```text
Use $qq-job-mail to draft an email to the address I provide, with an inline
image and an attachment. Show the complete saved draft before sending.
```

For general mail, edit `examples/mail.json` with a real recipient and your own files. `sample.png` is deliberately not bundled: supply an image or remove `html` and `inline_images` for a text-only example. The example recipient is non-deliverable documentation data.

```powershell
.\qq_job_mailer\run.ps1 prepare-mail .\examples\mail.json
.\qq_job_mailer\run.ps1 preview DRAFT_ID
.\qq_job_mailer\run.ps1 send DRAFT_ID
.\qq_job_mailer\run.ps1 records
```

Use `prepare TABLE.csv` for the job templates. Every send uses the shared history and asks for an exact confirmation. All attachment/inline source files together must be at most 15 MiB; MIME encoding adds size. One recipient per message; CC/BCC are not supported.

## Tests

```powershell
.\qq_job_mailer\.venv\Scripts\python.exe -m unittest discover -s .\qq_job_mailer -v
```

Tests use temporary files and mocked transport/credentials; they do not send real email. A Windows CI workflow runs offline tests with XLSX support. Real delivery depends on the user's account and network and must be verified with their own self-test.

## Privacy and limits

This repository intentionally excludes real configuration, credentials, resumes, screenshots, previews, delivery databases, exports, handoff archives and personal test messages. Credentials are tied to the local Windows user; other processes running as that user may access them. Do not upload local runtime files. Keep one active tool installation so duplicate protection remains centralized. Cloud conversations and other computers cannot automatically access a local skill or Windows credentials.

MIT licensed. See [LICENSE](LICENSE).
