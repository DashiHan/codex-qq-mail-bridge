# Privacy and publication

The public source is an allowlisted clean export, not a copy of an operational mailbox directory. No credentials are distributed. Windows Credential Manager is used only at runtime, without plaintext fallback. A process running as the same Windows user may access that user's credentials.

Do not commit generated config*.json, SQLite databases/WAL/SHM, previews/*.eml, delivery CSVs, resumes, mailbox screenshots, diagnostic captures, personal handoff notes, authorization codes or environment files. Ignore rules are a second layer, not a replacement for reviewing the actual Git index and history. Anonymous examples use reserved example domains. The release scanner rejects runtime artifacts and likely private contact data in the tracked release.

Use neutral Git author information if you do not want a local name/email embedded in commits. Repository ownership and GitHub platform account identity remain visible; publishing under an account is not anonymous. A source scrub cannot remove information already exposed in an unrelated account profile.

Before publishing a fork, run `python scripts/check_release.py` after staging the intended files, inspect `git diff --cached`, and inspect the commit author. Never add the original working directory or its archives wholesale.

If an authorization code is accidentally exposed, revoke it at the provider and obtain a new one locally. Removing a file from a later commit does not remove it from earlier Git history or third-party copies.
