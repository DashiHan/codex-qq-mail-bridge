"""Check tracked/indexed release files without opening local mail credentials."""
from pathlib import Path
import re
import subprocess

root = Path(__file__).resolve().parents[1]
result = subprocess.run(['git', 'ls-files', '-z'], cwd=root, capture_output=True, check=True)
paths = [Path(p.decode('utf-8')) for p in result.stdout.split(b'\0') if p]
if not paths:
    raise SystemExit('No tracked/indexed files to check; stage the release first.')
errors = []
for relative in paths:
    path = root / relative
    name = path.name.lower()
    if (name.startswith('config') and name.endswith('.json')) or any(x in relative.parts for x in ('previews', '__pycache__', '.venv', 'private', 'downloads', 'inbox-cache', 'replies')) or path.suffix.lower() in ('.eml', '.zip', '.sqlite3', '.db', '.pdf', '.pfx', '.key'):
        errors.append(str(relative) + ': runtime/private artifact')
    text = path.read_text(encoding='utf-8-sig')
    if re.search(r'[A-Za-z]:[\\/]Users[\\/][^\s]+', text, re.I):
        errors.append(str(relative) + ': private Windows user path')
    if re.search(r'(?<![0-9])1[3-9][0-9]{9}(?![0-9])', text):
        errors.append(str(relative) + ': possible private phone number')
    for local, domain in re.findall(r'([A-Za-z0-9_.+-]+)@([A-Za-z0-9.-]+\.[A-Za-z]{2,})', text):
        if domain.lower() in ('qq.com', 'foxmail.com', 'outlook.com') and (local.isdigit() or local.lower() not in ('sender', 'account', 'recipient')):
            # A tiny synthetic account is used solely by offline transport tests.
            if not (relative.name == 'test_mailer.py' and local == '123' and domain == 'qq.com'):
                errors.append(str(relative) + ': non-placeholder personal mailbox')
if errors:
    raise SystemExit('Release check failed:\n' + '\n'.join(errors))
print('Release check passed:', len(paths), 'tracked files; no runtime artifacts or private contacts detected.')
