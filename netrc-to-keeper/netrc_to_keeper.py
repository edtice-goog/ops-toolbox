#!/usr/bin/env python3
"""Convert .netrc files into a Keeper import file (Keeper's own CSV format), so the logins can move into a Keeper vault.

  PY -I netrc_to_keeper.py <netrc file or folder>... --list
                                           read-only: each login found (file, machine, login), never a password
  PY -I netrc_to_keeper.py <netrc file or folder>... --out <file.csv> [--folder NAME] [--force]
                                           write the import file

Keeper's importers don't read .netrc. This writes the format of Keeper's "Import Text File (.csv)" guide, one record
per netrc entry, no header row: Folder, Title, Login, Password, Website Address, Notes. Import it in Keeper (web vault:
the account menu > Settings > Import > Import, "Text File (.csv, .xls, and .tsv)", leave "file includes column headers"
unchecked), then delete the CSV. Nothing else is written, and nothing is deleted: once the records are in Keeper, delete
the netrc files yourself.

A folder means its *.netrc, .netrc and _netrc files (not its subfolders). The parser follows curl's and Python's netrc
rules: machine/default entries with login (or user), password and account; "quoted values" with backslash escapes; a #
comment where a keyword is expected; macdef blocks are skipped (they aren't logins). An error names the file and line,
never a value. The title is the file's name when it holds one entry (git-server.netrc -> git-server), else the
machine. The CSV is created new and, on Linux and macOS, readable by its owner only; on Windows it has its folder's
permissions, so write it somewhere only you can read.
Python 3.8+ standard library only. Tested with fakes only (test/test_netrc_to_keeper.py); the same CSV format, written
by another tool, imported cleanly into a Keeper web vault.
"""
import argparse
import csv
import datetime
import os
import sys

NETRC_NAMES = (".netrc", "_netrc")


class Fail(Exception):
    pass


class Lexer:
    """Whitespace-separated tokens; a "quoted value" may hold spaces and \\-escapes. Can skip the rest of a line (a
    comment) or a macro body (to the first empty line)."""

    def __init__(self, text, path):
        self.text, self.path, self.i, self.line = text, path, 0, 1

    def _space(self):
        while self.i < len(self.text) and self.text[self.i].isspace():
            if self.text[self.i] == "\n":
                self.line += 1
            self.i += 1

    def next(self):
        """(token, line, quoted), or None at the end."""
        self._space()
        t, n, start = self.text, len(self.text), self.line
        if self.i >= n:
            return None
        if t[self.i] != '"':
            j = self.i
            while j < n and not t[j].isspace():
                j += 1
            tok, self.i = t[self.i:j], j
            return tok, start, False
        self.i += 1
        out = []
        while True:
            if self.i >= n:
                raise Fail("%s, line %d: a quoted value has no closing quote" % (self.path, start))
            ch = t[self.i]
            self.i += 1
            if ch == '"':
                return "".join(out), start, True
            if ch == "\\" and self.i < n:
                ch = {"n": "\n", "r": "\r", "t": "\t"}.get(t[self.i], t[self.i])
                self.i += 1
            elif ch == "\n":
                self.line += 1
            out.append(ch)

    def _line_end(self):
        j = self.text.find("\n", self.i)
        return len(self.text) if j < 0 else j

    def skip_line(self):
        self.i = self._line_end()                              # the newline itself is counted by _space

    def skip_macro(self):
        """The rest of the macdef line, then every line up to the first empty one."""
        self.skip_line()
        while self.i < len(self.text):
            self.i += 1                                        # past the newline: the next line starts here
            self.line += 1
            end = self._line_end()
            empty = not self.text[self.i:end].strip()
            self.i = end
            if empty:
                return


def parse(path):
    """The entries of one netrc file: [{machine, login, password, account, line}] (machine None for `default`)."""
    try:
        with open(path, encoding="utf-8-sig") as f:
            text = f.read()
    except UnicodeDecodeError:
        raise Fail("%s: not UTF-8 text" % path)
    lex, entries, cur = Lexer(text, path), [], None

    def value(keyword, line):
        got = lex.next()
        if got is None:
            raise Fail("%s, line %d: %s has no value" % (path, line, keyword))
        return got[0]

    while True:
        got = lex.next()
        if got is None:
            return entries
        tok, line, quoted = got
        if quoted:
            raise Fail("%s, line %d: a quoted value where a keyword belongs" % (path, line))
        if tok.startswith("#"):
            lex.skip_line()                                    # a comment, to the end of its line
        elif tok == "machine":
            cur = {"machine": value("machine", line), "login": "", "password": None, "account": "", "line": line}
            entries.append(cur)
        elif tok == "default":
            cur = {"machine": None, "login": "", "password": None, "account": "", "line": line}
            entries.append(cur)
        elif tok in ("login", "user", "password", "account"):
            if cur is None:
                raise Fail("%s, line %d: %s before any machine or default" % (path, line, tok))
            cur["login" if tok == "user" else tok] = value(tok, line)
        elif tok == "macdef":
            value("macdef", line)                              # the macro's name; its body isn't a login
            lex.skip_macro()
            cur = None
        else:
            raise Fail("%s, line %d: an unknown keyword (not machine, default, login, user, password, account or "
                       "macdef)" % (path, line))


def netrc_files(paths):
    found = []
    for p in paths:
        if os.path.isdir(p):
            names = sorted(n for n in os.listdir(p) if n.endswith(".netrc") or n in NETRC_NAMES)
            found += [os.path.join(p, n) for n in names if os.path.isfile(os.path.join(p, n))]
        elif os.path.isfile(p):
            found.append(p)
        else:
            raise Fail("%s: no such file or folder" % p)
    if not found:
        raise Fail("no netrc file found in %s" % ", ".join(paths))
    return found


def records(files, folder):
    """Keeper import rows: Folder, Title, Login, Password, Website Address, Notes."""
    today = datetime.date.today().isoformat()
    rows, seen = [], set()
    for path in files:
        entries = parse(path)
        name = os.path.basename(path)
        stem = name[:-len(".netrc")] if name.endswith(".netrc") and len(name) > len(".netrc") else name
        for e in entries:
            machine = e["machine"]
            title = stem if len(entries) == 1 else (machine or "default (any host)")
            if title in seen:
                title = "%s (%s)" % (title, e["login"] or "line %d" % e["line"])
            seen.add(title)
            site = "" if not machine else machine if "://" in machine else "https://" + machine
            note = "From %s (netrc, %s), converted %s" % (name, "machine %s" % machine if machine else "default",
                                                         today)
            if e["account"]:
                note += "; account: %s" % e["account"]
            rows.append({"row": [folder, title, e["login"], e["password"] or "", site, note],
                         "file": path, "machine": machine or "default", "login": e["login"],
                         "password": e["password"] is not None})
    return rows


def write_csv(out, rows, force):
    if os.path.exists(out) and not force:
        raise Fail("%s exists: choose another --out, or --force to replace it" % out)
    if os.path.exists(out):
        os.remove(out)
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, quoting=csv.QUOTE_ALL)
        for r in rows:
            w.writerow(r["row"])


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("paths", nargs="+", help="netrc files, or folders holding them")
    ap.add_argument("--list", action="store_true", help="only list the logins found (no password); writes nothing")
    ap.add_argument("--out", help="the Keeper import file to write (.csv)")
    ap.add_argument("--folder", default="netrc", help='the Keeper folder the records land in (default "netrc"; '
                                                      'subfolders with a backslash, as in Keeper\'s own format)')
    ap.add_argument("--force", action="store_true", help="replace --out if it exists")
    a = ap.parse_args(argv)
    try:
        if not a.list and not a.out:
            raise Fail("say --out <file.csv> (or --list to only see what is there)")
        files = netrc_files(a.paths)
        rows = records(files, a.folder)
        for r in rows:
            print("  %-40s %-34s login %-20s %s" % (r["file"], r["machine"], r["login"] or "-",
                                                     "password" if r["password"] else "NO PASSWORD"))
        if a.list:
            print("%d login(s) in %d file(s); nothing written." % (len(rows), len(files)))
            return 0
        if not rows:
            raise Fail("no login in %s: nothing written" % ", ".join(files))
        write_csv(a.out, rows, a.force)
    except Fail as e:
        print("netrc_to_keeper: %s" % e, file=sys.stderr)
        return 2
    print("", "Wrote %d record(s) to %s, for Keeper's folder %s. No password was shown." % (len(rows), a.out, a.folder),
          "Import it: Keeper web vault, the account menu (your e-mail address, top right) > Settings > Import > Import",
          '(next to "Use Another Source"), choose "Text File (.csv, .xls, and .tsv)", drop the file on it, leave "file',
          'includes column headers" unchecked (it has none), check that the columns map to Folder, Title, Login,',
          "Password, Website Address, Notes, then Next and Confirm Import.",
          "", "Then delete %s, and, once each record is in Keeper, the netrc files:" % a.out,
          *("  %s" % f for f in files), "This script deleted nothing.", sep="\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
