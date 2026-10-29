"""Offline tests of teams_cache.py: fakes only, no Teams. A scratch folder stands for %LOCALAPPDATA% (Windows) or ~
(macOS), and a file stands for the process list.  python teams-cache/test/test_teams_cache.py"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

TOOL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "teams_cache.py")


def files_under(path):
    return sorted(os.path.relpath(os.path.join(r, f), path) for r, _, fs in os.walk(path) for f in fs)


class Base(unittest.TestCase):
    PLATFORM = "win"

    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.ps = os.path.join(self.home, "ps.txt")
        open(self.ps, "w").close()

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def put(self, *parts, text="x"):
        p = os.path.join(self.home, *parts)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
        return p

    def run_tool(self, *args):
        env = dict(os.environ, TEAMS_CACHE_PLATFORM=self.PLATFORM, TEAMS_CACHE_HOME=self.home, TEAMS_CACHE_PS=self.ps,
                   APPDATA=os.path.join(self.home, "Roaming"))
        p = subprocess.run([sys.executable, "-I", TOOL] + list(args), capture_output=True, text=True, env=env)
        return p.returncode, p.stdout + p.stderr

    def teams_running(self, on=True):
        with open(self.ps, "w", encoding="utf-8") as f:
            f.write(("ms-teams.exe" if self.PLATFORM == "win" else "MSTeams") + "\n" if on else "")

    def is_running(self):
        with open(self.ps, encoding="utf-8") as f:
            return bool(f.read().strip())


class TestWindows(Base):
    CACHE = ("Packages", "MSTeams_8wekyb3d8bbwe", "LocalCache", "Microsoft", "MSTeams")

    def cache(self):
        self.put(*self.CACHE, "EBWebView", "Default", "IndexedDB", "db", text="y" * 2000)
        self.put(*self.CACHE, "app_settings.json", text="{}")
        self.put(*self.CACHE, "Backgrounds", "Uploads", "mine.png", text="png")
        return os.path.join(self.home, *self.CACHE)

    def test_check_reads_only(self):
        cache = self.cache()
        self.teams_running()
        before = files_under(self.home)
        rc, o = self.run_tool("check")
        self.assertEqual(rc, 0, o)
        self.assertIn("Teams: installed", o)
        self.assertIn("RUNNING", o)
        self.assertIn("Cache: 0.0 MB in %s" % cache, o)
        self.assertIn("Custom backgrounds: kept in place", o)
        self.assertEqual(files_under(self.home), before)

    def test_clear_refuses_while_teams_runs(self):
        self.cache()
        self.teams_running()
        before = files_under(self.home)
        rc, o = self.run_tool("clear")
        self.assertEqual(rc, 2, o)
        self.assertIn("run this again with --stop, which ends it", o)
        self.assertIn("Nothing was moved", o)
        self.assertEqual(files_under(self.home), before)

    def test_clear_with_stop_moves_the_cache_aside_keeps_backgrounds_and_starts_teams(self):
        cache = self.cache()
        self.teams_running()
        before = files_under(self.home)
        rc, o = self.run_tool("clear", "--stop")
        self.assertEqual(rc, 0, o)
        self.assertIn("Teams: ended", o)
        self.assertEqual(os.listdir(cache), ["Backgrounds"])                 # the user's own backgrounds stay
        [backup] = [n for n in os.listdir(os.path.dirname(cache)) if n.startswith("MSTeams.old-")]
        backup = os.path.join(os.path.dirname(cache), backup)
        self.assertEqual(sorted(os.listdir(backup)), ["EBWebView", "app_settings.json"])
        self.assertIn("Moved 2 item(s) of the cache into %s" % backup, o)
        self.assertIn("the user may delete %s" % backup, o)
        self.assertEqual(len(files_under(self.home)), len(before))           # nothing deleted, only moved
        self.assertTrue(self.is_running(), "Teams is started again")
        rc, o = self.run_tool("check")
        self.assertIn("Earlier backup: %s" % backup, o)
        self.assertIn("Cache: empty", o)

    def test_no_start_leaves_teams_closed(self):
        self.cache()
        rc, o = self.run_tool("clear", "--no-start")
        self.assertEqual(rc, 0, o)
        self.assertFalse(self.is_running())
        self.assertNotIn("Teams: started", o)

    def test_not_installed(self):
        rc, o = self.run_tool("check")
        self.assertEqual(rc, 1)
        self.assertIn("New Teams is not installed", o)
        rc, o = self.run_tool("clear")
        self.assertEqual(rc, 1)
        self.assertIn("nothing to clear", o)

    def test_classic_teams_is_named_and_left_alone(self):
        self.cache()
        classic = self.put("Roaming", "Microsoft", "Teams", "Cache", "f")
        rc, o = self.run_tool("check")
        self.assertIn("Classic Teams data is here too", o)
        self.run_tool("clear")
        self.assertTrue(os.path.exists(classic))


class TestMac(Base):
    PLATFORM = "mac"

    def test_clear_moves_both_folders_into_application_support(self):
        self.put("Library", "Group Containers", "UBF8T346G9.com.microsoft.teams", "a", text="1")
        self.put("Library", "Containers", "com.microsoft.teams2", "Data", "b", text="2")
        os.makedirs(os.path.join(self.home, "Library", "Application Support"))
        before = files_under(self.home)
        rc, o = self.run_tool("check")
        self.assertEqual(rc, 0, o)
        self.assertIn("not running", o)
        rc, o = self.run_tool("clear")
        self.assertEqual(rc, 0, o)
        support = os.path.join(self.home, "Library", "Application Support")
        [backup] = [n for n in os.listdir(support) if n.startswith("MSTeams-cache.old-")]
        self.assertEqual(sorted(os.listdir(os.path.join(support, backup))),
                         ["UBF8T346G9.com.microsoft.teams", "com.microsoft.teams2"])
        self.assertFalse(os.path.exists(os.path.join(self.home, "Library", "Containers", "com.microsoft.teams2")))
        self.assertEqual(len(files_under(self.home)), len(before))
        self.assertTrue(self.is_running())


class TestOther(Base):
    PLATFORM = "other"

    def test_says_the_browser_is_the_client(self):
        rc, o = self.run_tool("check")
        self.assertEqual(rc, 1)
        self.assertIn("Teams runs in the browser here", o)


if __name__ == "__main__":
    unittest.main()
