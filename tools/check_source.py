"""Reject local data, credentials, and machine-specific files from the source tree."""
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
BLOCKED_DIRS = {
    '.venv', '.git', '__pycache__', '.pytest_cache', '.codex', '.claude', '.agents',
    'models', 'runtime', 'output', 'captures', 'handoff', 'downloads', 'node_modules',
}
BLOCKED_SUFFIXES = {
    '.pt', '.onnx', '.bin', '.dll', '.exe', '.pyc', '.cs8', '.cu8', '.lnk',
    '.zip', '.7z', '.log', '.jsonl', '.sigmf-data', '.sigmf-meta',
}
README_MEDIA = {'docs/media/tracking.gif', 'docs/media/workspace.gif'}
CONTENT_RULES = {
    'machine-specific path': re.compile(r'[A-Z]:[\\/](?:Users|devProject)[\\/]', re.I),
    'private key': re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    'access token': re.compile(r'(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|sk-proj-[A-Za-z0-9_-]{30,})'),
    'conversation reference': re.compile(r'(?:codex:[/]{2}threads[/]|source_thread\s*[\"\x27]?\s*:)'),
}


def main():
    result = subprocess.run(
        ['git', 'ls-files', '-z', '--cached', '--others', '--exclude-standard'],
        cwd=ROOT, check=True, capture_output=True,
    )
    names = sorted(set(result.stdout.decode('utf-8').rstrip('\0').split('\0')) - {''})
    errors = []
    for name in names:
        path = Path(name)
        lower = name.lower()
        if (set(part.lower() for part in path.parts) & BLOCKED_DIRS
                or path.suffix.lower() in BLOCKED_SUFFIXES
                or lower.startswith(('assets/replay/', 'assets/satellite/vendor/'))
                or path.name.lower() in {'agents.md', 'claude.md', 'settings.json', '.env'}):
            errors.append(f'{name}: local or private file')
            continue
        data = (ROOT / path).read_bytes()
        if name in README_MEDIA:
            if not data.startswith((b'GIF87a', b'GIF89a')) or len(data) > 8_000_000:
                errors.append(f'{name}: expected a GIF smaller than 8 MB')
            continue
        if len(data) > 2_000_000:
            errors.append(f'{name}: unexpected large source file')
        try:
            content = data.decode('utf-8-sig')
        except UnicodeDecodeError:
            errors.append(f'{name}: unexpected binary file')
            continue
        for label, pattern in CONTENT_RULES.items():
            if pattern.search(content):
                errors.append(f'{name}: {label}')
    if errors:
        print('\n'.join(errors), file=sys.stderr)
        return 1
    print(f'Source check passed: {len(names)} files; no private assets or local state.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
