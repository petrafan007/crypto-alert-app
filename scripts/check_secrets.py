"""Fail release checks on tracked private env files or Telegram token literals."""
import pathlib
import re
import subprocess
import sys

root = pathlib.Path(__file__).resolve().parents[1]
paths = subprocess.check_output(['git', 'ls-files', '-z'], cwd=root).decode().split('\0')
pattern = re.compile(rb'(?<![0-9])[0-9]{7,12}:[A-Za-z0-9_-]{30,50}')
failed = []
for name in filter(None, paths):
    path = root / name
    if not path.is_file():
        continue
    if (path.name == '.env' or path.name.startswith('.env.')) and path.name != '.env.example':
        failed.append((name, 'private environment file is tracked'))
    elif pattern.search(path.read_bytes()):
        failed.append((name, 'Telegram token literal detected'))
for name, reason in failed:
    print(f'{name}: {reason}')
if failed:
    sys.exit(1)
print('Tracked-file secret checks passed.')
