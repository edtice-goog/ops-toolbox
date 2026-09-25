"""Render a Claude Code session transcript (.jsonl, e.g. from the desktop app's session Export) as a readable
conversation for someone who was not there.

Keeps: the user's messages (including ones sent while Claude was working, and pasted terminal output, shown boxed),
Claude's replies (intermediate status notes in a lighter style, the final reply of each turn in full), multiple-choice
questions with their answers, interruptions. Replaces each stretch of tool calls by one line ("12 tool calls, output
omitted: Bash 10, Read 2"), notes tool calls that were blocked by a permission check, and shows in full any command
that talks to a git remote (push/fetch/remote add/remove), because a reviewer usually cares about those.
Drops: tool output, internal reasoning, app bookkeeping.

usage: python render_conversation.py transcript.jsonl out.md [--title T] [--subtitle S] [--intro-file F]
                                     [--user-name NAME] [--stop-at TEXT]
then, for example:
  pandoc out.md -t html5 --standalone --embed-resources --css conversation.css -o out.html
  pandoc out.md -t docx -o out.docx
Redact the transcript first (redact.py) if secrets ever appeared in it."""
import argparse
import json
import re

ap = argparse.ArgumentParser()
ap.add_argument('src')
ap.add_argument('dst')
ap.add_argument('--title', default='Claude Code session')
ap.add_argument('--subtitle', default='')
ap.add_argument('--intro-file', help='Markdown inserted after the title (context, outcome)')
ap.add_argument('--user-name', default='User')
ap.add_argument('--stop-at', help='stop before the first user message containing this text')
args = ap.parse_args()

PASTE = re.compile(r'<pasted_content[^>]*>\n?(.*?)\n?</pasted_content[^>]*>', re.S)
NOTABLE = re.compile(r'git (-C \S+ )?(push|fetch)|remote (add|remove)')

events = []   # (kind, timestamp, payload)
results = {}  # tool_use_id -> output text
for line in open(args.src, encoding='utf-8'):
    d = json.loads(line)
    ts = d.get('timestamp', '')[:16].replace('T', ' ')
    kind, msg = d.get('type'), d.get('message')
    if kind == 'attachment' and d.get('attachment', {}).get('type') == 'queued_command':
        events.append(('user-midturn', ts, d['attachment'].get('prompt', '')))
        continue
    if kind not in ('user', 'assistant') or not isinstance(msg, dict) or d.get('isSidechain'):
        continue
    content = msg.get('content')
    if kind == 'user' and isinstance(content, str):
        events.append(('user', ts, content))
        continue
    for b in content or []:
        if not isinstance(b, dict):
            continue
        t = b.get('type')
        if kind == 'user' and t == 'text':
            events.append(('interrupt' if 'interrupted' in b['text'] else 'user', ts, b['text']))
        elif kind == 'assistant' and t == 'text' and b.get('text', '').strip():
            events.append(('claude', ts, b['text']))
        elif kind == 'assistant' and t == 'tool_use':
            if b.get('name') == 'AskUserQuestion':
                events.append(('question', ts, b.get('input', {})))
            else:
                events.append(('tool', ts, {'id': b.get('id'), 'name': b.get('name'), 'input': b.get('input', {})}))
        elif kind == 'user' and t == 'tool_result':
            body = b.get('content')
            body = body if isinstance(body, str) else ' '.join(c.get('text', '') for c in body or [] if isinstance(c, dict))
            results[b.get('tool_use_id')] = body
            if 'have been answered' in body:
                events.append(('answer', ts, body))


def flush(names):
    if not names:
        return []
    counts = {}
    for n in names:
        n = n.split('__')[-1]
        counts[n] = counts.get(n, 0) + 1
    detail = ', '.join('%s %d' % (k, v) for k, v in sorted(counts.items(), key=lambda kv: -kv[1]))
    return ['::: work', '[%d tool call%s, output omitted: %s]' % (len(names), 's' if len(names) > 1 else '', detail), ':::', '']


def demote(md, levels=3):
    """Push a reply's own headings below the document's message headings; leave code blocks alone."""
    out, fence = [], None
    for line in md.split('\n'):
        m = re.match(r'^(```|~~~)', line)
        if m:
            fence = None if fence == m.group(1) else (fence or m.group(1))
        if fence is None and re.match(r'^#{1,6} ', line):
            line = re.sub(r'^#{7,}', '######', '#' * levels + line)
        out.append(line)
    return '\n'.join(out)


def user_block(text, ts, label):
    text, pos = text.strip(), 0
    lines = ['## %s · %s UTC' % (label, ts), '']
    for m in PASTE.finditer(text):
        before = text[pos:m.start()].strip()
        if before:
            lines += [before, '']
        lines += ['*Pasted terminal output:*', '', '~~~~', m.group(1).rstrip(), '~~~~', '']
        pos = m.end()
    rest = text[pos:].strip()
    return lines + ([rest, ''] if rest else [])


out = ['---', 'title: %s' % json.dumps(args.title)] + (['subtitle: %s' % json.dumps(args.subtitle)] if args.subtitle else []) + ['---', '']
if args.intro_file:
    out += [open(args.intro_file, encoding='utf-8').read().strip(), '']

i, n = 0, len(events)
while i < n:
    kind, ts, payload = events[i]
    if kind == 'user' and args.stop_at and args.stop_at in payload:
        break
    if kind in ('user', 'user-midturn'):
        label = args.user_name + (' (sent while Claude was working)' if kind == 'user-midturn' else '')
        out += user_block(payload, ts, label)
        i += 1
        continue
    if kind == 'interrupt':
        out += ['*%s interrupted the command Claude was running.*' % args.user_name, '']
        i += 1
        continue
    j = i
    while j < n and events[j][0] not in ('user', 'user-midturn', 'interrupt'):
        j += 1
    stretch = events[i:j]
    last_text = max((k for k, e in enumerate(stretch) if e[0] == 'claude'), default=None)
    out += ['## Claude · %s UTC' % ts, '']
    tools = []
    for k, (ekind, ets, epayload) in enumerate(stretch):
        if ekind == 'tool':
            inp = epayload['input'] if isinstance(epayload['input'], dict) else {}
            cmd, result = inp.get('command', ''), results.get(epayload['id'], '')
            if NOTABLE.search(cmd) and 'denied' not in result:
                out += flush(tools); tools = []
                out += ['*Claude ran against a git remote:* ' + inp.get('description', ''), '',
                        '~~~~', '$ ' + cmd.strip(), '', result.strip(), '~~~~', '']
            elif 'Permission for this action was denied' in result:
                out += flush(tools); tools = []
                out += ['::: work', '[blocked by a permission check: %s]' % (inp.get('description') or epayload['name']), ':::', '']
            else:
                tools.append(epayload['name'])
            continue
        out += flush(tools); tools = []
        if ekind == 'claude':
            if k == last_text:
                out += [demote(epayload.strip()), '']
            else:
                out += ['::: note', '*Progress note:* ' + epayload.strip(), ':::', '']
        elif ekind == 'question':
            for q in epayload.get('questions', []):
                out += ['**Claude asked:** ' + q.get('question', ''), '']
                out += ['- **%s**: %s' % (o.get('label'), o.get('description')) for o in q.get('options', [])] + ['']
        elif ekind == 'answer':
            m = re.search(r'="([^"]+)"\.', epayload)
            out += ['**%s chose:** %s' % (args.user_name, m.group(1) if m else epayload), '']
    out += flush(tools)
    i = j

open(args.dst, 'w', encoding='utf-8', newline='\n').write('\n'.join(out) + '\n')
print('wrote %s: %d blocks from %d events' % (args.dst, len(out), n))
