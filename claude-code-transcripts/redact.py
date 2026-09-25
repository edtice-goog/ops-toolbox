"""Redact secrets from an unpacked Claude Code session export (or any directory of text files) before sharing it.

usage: python redact.py <directory> <secrets-file>
The secrets file has one secret per line, optionally "label<TAB>value"; build it from wherever the secrets live
(e.g. a script that reads them from the tracked files), never by pasting into a chat. Values are never printed:
the report gives counts per label, then a verification pass that must end with "remaining occurrences: 0".
Also replaced, without a secrets file entry:
  - crypt/htpasswd hashes ($5$, $6$, $apr1$, $2y$ ...)
  - the 6-character prefix of any secret of 12+ characters (people and models write "abc123..." when referring
    to a value)
Files are rewritten in place, so run it on a copy."""
import glob
import os
import re
import sys

root, secrets_file = sys.argv[1], sys.argv[2]
secrets = {}
for line in open(secrets_file, encoding='utf-8'):
    line = line.rstrip('\r\n')
    if not line.strip() or line.startswith('#'):
        continue
    label, _, value = line.partition('\t') if '\t' in line else ('secret', '', line)
    if len(value) >= 6:
        secrets.setdefault(value, label)

HASH = re.compile(r'\$(?:1|2[aby]|5|6|apr1)\$[A-Za-z0-9./]+\$[A-Za-z0-9./]+')
files = [f for f in glob.glob(os.path.join(root, '**', '*'), recursive=True) if os.path.isfile(f)]
totals = {}
for f in files:
    raw = open(f, 'rb').read()
    try:
        text = raw.decode('utf-8')
    except UnicodeDecodeError:
        print('skipped (not UTF-8 text): %s' % f)
        continue
    for value, label in sorted(secrets.items(), key=lambda kv: -len(kv[0])):
        for needle, tag in ((value, label), (value[:6] if len(value) >= 12 else None, label + ' (prefix)')):
            if needle and needle in text:
                totals[tag] = totals.get(tag, 0) + text.count(needle)
                text = text.replace(needle, '[REDACTED: %s]' % label)
    text, count = HASH.subn('[hash redacted]', text)
    if count:
        totals['password hashes'] = totals.get('password hashes', 0) + count
    open(f, 'wb').write(text.encode('utf-8'))

print('secrets loaded: %d' % len(secrets))
for label, count in sorted(totals.items()):
    print('  replaced %5d  %s' % (count, label))
left = 0
for f in files:
    try:
        text = open(f, encoding='utf-8').read()
    except UnicodeDecodeError:
        continue
    left += sum(text.count(v) + (text.count(v[:6]) if len(v) >= 12 else 0) for v in secrets) + len(HASH.findall(text))
print('remaining occurrences: %d' % left)
