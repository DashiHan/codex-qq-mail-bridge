# Command reference / 命令说明

Run commands through `qq_job_mailer/run.ps1`, or `python qq_job_mailer/mailer.py` using your chosen interpreter. All local state is relative to the tool file, not the shell's current directory.

| Command | Effect |
| --- | --- |
| doctor | Check Python/XLSX support and verified TLS to QQ SMTP; no login or sending |
| setup | Interactive account/profile/resumes and hidden authorization code; closes formal-delivery gate |
| test | Prepare and individually approve a self-addressed transport test |
| confirm-test | Enable delivery only after a submitted test and your actual receipt confirmation |
| prepare TABLE | Validate CSV/XLSX and save job application drafts |
| prepare-mail JSON | Save one general mail draft, never sends |
| preview ID | Display the saved draft |
| send ID | Check files, authorization gate, exact confirmation, interval and duplicates; submit once |
| records | Export local 投递记录.csv |
| resolve RECORD | Manually resolve uncertain/in-progress attempts after investigation |
| forget | Remove this tool's Windows authorization credential and disable formal sending |

## General mail JSON

`to`, `subject`, `body` are required. Optional `html` provides an HTML alternative to plain text. `attachments` is an array of paths. `inline_images` contains objects with `path` and a unique simple `cid` matching an HTML `cid:` image reference. Relative paths resolve against the JSON file directory. Examples use reserved example.org addresses; replace them yourself. Total file bytes <=15 MiB. MIME serialization/base64 adds overhead.

## Job tables

CSV: UTF-8 or UTF-8 BOM. XLSX: first sheet, values only, no formulas. Required: 单位,岗位,性质,邮箱. Optional: 联系人,简历路径,主题. 性质: 高校/研究所/企业. A job email includes one existing PDF with a valid PDF header, at most15 MiB. Relative resume paths resolve against the table directory.

## Changing the outward sender

`account` remains a full @qq.com authentication account and the credential/history key. Optional `sender` is a QQ/Foxmail address belonging to that same account. Server policy decides whether an alias is accepted. Headers, SMTP envelope and template signature all use sender. Do not change account just to select an alias.

After an enabled account changes sender, reset the test gate and timestamp before testing. One method is to rerun setup yourself, which disables formal sending and refreshes configured_epoch, then add sender to config.json again before test / confirm-test. Keep the same tool directory and account so all previous delivery attempts remain intact. Old drafts with another From address are rejected. Editing sender alone does not reset the gate automatically; take this step explicitly.

## Failure and state

SMTP rejection: failed; fix the cause, then review again. Timeout/disconnection: uncertain; the message may have been submitted. No automatic retry. An empty Sent folder does not prove failure: SMTP submissions are not guaranteed to appear there. Resolve only after checking the mailbox/bounces or otherwise investigating. Never delete SQLite state to bypass duplicates.

Job duplicate keys use account/unit/role/recipient; general mail uses account/sender/recipient/subject/body/HTML/file hashes and paths. Identical general mail is blocked even when prepared again. Changed paths or text can create a different key; manually verify intent. All attempts for an account share the minimum interval. Keep a single active installation. Back up the full local directory with processes stopped; do not rely on CSV as the database backup.

Templates, personal profiles, config, previews, history and resumes may contain private data once used. Do not publish those runtime files. Re-running setup changes configuration and closes the sending gate; credentials do not migrate to another Windows user/computer by copying files.
