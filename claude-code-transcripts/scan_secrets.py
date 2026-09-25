"""Second-opinion scan after redact.py: lists anything that still looks like a credential assignment, a credential
in a URL, or a private key, with the value MASKED (first two characters and length). Read-only.
usage: python scan_secrets.py <directory>
Expect false positives (code such as password = $variable, lab values); read each hit in context before sharing."""
import collections
import glob
import os
import re
import sys

ASSIGN = re.compile(r"(?i)(password|passwd|token|secret|apikey|api_key)[A-Za-z_]*\\*[\"']?\s*(?:=>|=|:)\s*\\*[\"']([^\"'\\\s<>\[\]{}()]{8,})")
URL = re.compile(r"(?i)(apikey=|://[A-Za-z0-9_.-]+:)([^@&\s\"'\\]{8,})")
seen = collections.Counter()
for f in glob.glob(os.path.join(sys.argv[1], '**', '*'), recursive=True):
    if not os.path.isfile(f):
        continue
    try:
        text = open(f, encoding='utf-8').read()
    except UnicodeDecodeError:
        continue
    for regex, kind in ((ASSIGN, None), (URL, 'url')):
        for m in regex.finditer(text):
            value = m.group(2)
            seen[(kind or m.group(1).lower(), m.group(1)[:16] if kind else '', value[:2] + '*' * (len(value) - 2))] += 1
    if 'PRIVATE KEY-----' in text:
        seen[('private key block', os.path.basename(f), '')] += text.count('PRIVATE KEY-----')
for key, count in sorted(seen.items(), key=lambda kv: -kv[1]):
    print(count, key)
print('(end of scan)')
