"""Offline tests of netrc_to_keeper.py: fakes only, in a scratch folder.  python netrc-to-keeper/test/test_netrc_to_keeper.py"""
import csv
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

TOOL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "netrc_to_keeper.py")
SECRET = "Fake-Pw-NEVER-SHOWN-1"


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.out = os.path.join(self.dir, "out", "keeper-import.csv")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def put(self, name, text):
        p = os.path.join(self.dir, name)
        with open(p, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        return p

    def run_tool(self, *args):
        p = subprocess.run([sys.executable, "-I", TOOL] + list(args), capture_output=True, text=True)
        return p.returncode, p.stdout + p.stderr

    def rows(self):
        with open(self.out, encoding="utf-8", newline="") as f:
            return list(csv.reader(f))

    def text(self):
        with open(self.out, encoding="utf-8") as f:
            return f.read()


class TestConvert(Base):
    def test_one_entry_per_file_takes_the_files_name(self):
        self.put("git-server.netrc", "machine git.example.com login alice password %s\n" % SECRET)
        self.put("repo.example.com.netrc", "machine repo.example.com\n  login svc\n  password other-fake-pw\n")
        self.put("notes.txt", "machine skipped.example.com login x password y\n")      # not a netrc file
        rc, o = self.run_tool(self.dir, "--out", self.out)
        self.assertEqual(rc, 0, o)
        self.assertNotIn(SECRET, o)
        self.assertNotIn("other-fake-pw", o)
        rows = {r[1]: r for r in self.rows()}
        self.assertEqual(sorted(rows), ["git-server", "repo.example.com"])
        r = rows["git-server"]
        self.assertEqual(r[:5], ["netrc", "git-server", "alice", SECRET, "https://git.example.com"])
        self.assertIn("From git-server.netrc (netrc, machine git.example.com)", r[5])
        self.assertTrue(all(len(x) == 6 for x in self.rows()))                     # Keeper's six columns, no header
        self.assertIn("This script deleted nothing.", o)
        self.assertIn(os.path.join(self.dir, "git-server.netrc"), o)            # listed for the user to delete
        self.assertTrue(os.path.isfile(os.path.join(self.dir, "git-server.netrc")))

    def test_several_entries_quotes_comments_macdef_default(self):
        self.put(".netrc", "\n".join([
            "# my logins",
            "machine a.example.com login alice password \"two words \\\"quoted\\\"\"",
            "machine a.example.com user bob password #starts-with-hash   # a password, not a comment",
            "macdef init",
            "  cd \"unclosed quote in a macro",
            "  password not-a-login",
            "",
            "default login anon password =formula-looking account acct-1",
            ""]))
        rc, o = self.run_tool(os.path.join(self.dir, ".netrc"), "--out", self.out, "--folder", "Keys\\netrc")
        self.assertEqual(rc, 0, o)
        rows = self.rows()
        self.assertEqual([r[1] for r in rows], ["a.example.com", "a.example.com (bob)", "default (any host)"])
        self.assertEqual(rows[0][3], 'two words "quoted"')
        self.assertEqual(rows[1][2:4], ["bob", "#starts-with-hash"])
        self.assertEqual(rows[2][2:5], ["anon", "=formula-looking", ""])
        self.assertIn("account: acct-1", rows[2][5])
        self.assertEqual({r[0] for r in rows}, {"Keys\\netrc"})
        self.assertNotIn("not-a-login", self.text())

    def test_list_writes_nothing_and_shows_no_password(self):
        self.put("x.netrc", "machine h.example.com login l password %s\nmachine g.example.com login m\n" % SECRET)
        rc, o = self.run_tool(self.dir, "--list")
        self.assertEqual(rc, 0, o)
        self.assertNotIn(SECRET, o)
        self.assertIn("NO PASSWORD", o)
        self.assertIn("2 login(s) in 1 file(s); nothing written.", o)
        self.assertFalse(os.path.exists(self.out))

    def test_an_existing_output_is_kept_unless_forced(self):
        self.put("x.netrc", "machine h.example.com login l password p\n")
        os.makedirs(os.path.dirname(self.out))
        with open(self.out, "w") as f:
            f.write("keep me")
        rc, o = self.run_tool(self.dir, "--out", self.out)
        self.assertEqual(rc, 2)
        self.assertIn("exists", o)
        self.assertEqual(self.text(), "keep me")
        rc, o = self.run_tool(self.dir, "--out", self.out, "--force")
        self.assertEqual(rc, 0, o)
        self.assertEqual(self.rows()[0][3], "p")

    @unittest.skipIf(os.name == "nt", "POSIX permissions")
    def test_the_csv_is_its_owners_only(self):
        self.put("x.netrc", "machine h.example.com login l password p\n")
        self.run_tool(self.dir, "--out", self.out)
        self.assertEqual(os.stat(self.out).st_mode & 0o777, 0o600)


class TestErrors(Base):
    def test_errors_name_the_line_never_a_value(self):
        cases = {
            "unknown.netrc": ("machine h login l passwd %s\n" % SECRET, "line 1: an unknown keyword"),
            "early.netrc": ("password %s\n" % SECRET, "line 1: password before any machine"),
            "open.netrc": ('machine h login l\npassword "%s\n' % SECRET, "line 2: a quoted value has no closing"),
            "short.netrc": ("machine h login l password", "line 1: password has no value"),
        }
        for name, (text, want) in cases.items():
            path = self.put(name, text)
            rc, o = self.run_tool(path, "--out", self.out)
            self.assertEqual(rc, 2, name)
            self.assertIn(want, o, name)
            self.assertNotIn(SECRET, o, name)
            self.assertFalse(os.path.exists(self.out), name)

    def test_needs_out_or_list(self):
        self.put("x.netrc", "machine h login l password p\n")
        rc, o = self.run_tool(self.dir)
        self.assertEqual(rc, 2)
        self.assertIn("--out", o)


if __name__ == "__main__":
    unittest.main()
