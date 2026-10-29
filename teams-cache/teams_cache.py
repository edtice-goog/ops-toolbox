#!/usr/bin/env python3
"""Clear the local cache of the Microsoft Teams desktop client (new Teams) when messages stop sending or arriving.

  PY -I teams_cache.py check               read-only: is Teams installed and running, its cache, earlier backups
  PY -I teams_cache.py clear [--stop] [--no-start]
                                           with Teams quit: move the cache aside, then start Teams again

Nothing is deleted: the cache moves into a backup folder beside it (Windows) or in Application Support (macOS), which
the user deletes once Teams works. Teams rebuilds its cache on the next start. `--stop` ends a running Teams first,
with every process under it (only after the user's yes: an unsent draft can be lost); Teams' own Quit often leaves it
running. Custom backgrounds stay in place on Windows.
Windows and macOS; Python 3.8+ standard library only. The paths are the new Teams' (the classic client is retired).
"""
import argparse
import os
import subprocess
import sys
import time

# TEAMS_CACHE_* are for test/test_teams_cache.py only: the platform, the home that stands for %LOCALAPPDATA% or ~, and a
# file that stands for the process list (one name per line)
PLATFORM = os.environ.get("TEAMS_CACHE_PLATFORM") or ("win" if os.name == "nt" else "mac" if sys.platform == "darwin"
                                                    else "other")
FAKE_PS = os.environ.get("TEAMS_CACHE_PS")
WIN_PACKAGE = "MSTeams_8wekyb3d8bbwe"
WIN_PROCESS = "ms-teams.exe"
MAC_PROCESS = "MSTeams"
KEEP = {"Backgrounds"}          # Windows: the user's own backgrounds, in the cache folder; they stay


def home():
    if os.environ.get("TEAMS_CACHE_HOME"):
        return os.environ["TEAMS_CACHE_HOME"]
    return os.environ.get("LOCALAPPDATA", "") if PLATFORM == "win" else os.path.expanduser("~")


def layout():
    """(what to move: [paths], where backups go, the installed client's folder)"""
    h = home()
    if PLATFORM == "win":
        package = os.path.join(h, "Packages", WIN_PACKAGE)
        cache = os.path.join(package, "LocalCache", "Microsoft", "MSTeams")
        return [cache], os.path.dirname(cache), package
    if PLATFORM == "mac":
        lib = os.path.join(h, "Library")
        return ([os.path.join(lib, "Group Containers", "UBF8T346G9.com.microsoft.teams"),
                 os.path.join(lib, "Containers", "com.microsoft.teams2")],
                os.path.join(lib, "Application Support"), os.path.join(lib, "Containers", "com.microsoft.teams2"))
    return [], "", ""


def backup_prefix():
    return "MSTeams.old-" if PLATFORM == "win" else "MSTeams-cache.old-"


def size(path):
    total = 0
    for root, _, files in os.walk(path):
        for f in files:
            try:
                total += os.lstat(os.path.join(root, f)).st_size
            except OSError:
                pass
    return total


def mb(n):
    return "%.0f MB" % (n / 1e6) if n >= 1e6 else "%.1f MB" % (n / 1e6)


def running():
    """True while the Teams client runs."""
    if FAKE_PS is not None:
        try:
            with open(FAKE_PS, encoding="utf-8") as f:
                names = {line.strip().lower() for line in f if line.strip()}
        except OSError:
            names = set()
        return (WIN_PROCESS if PLATFORM == "win" else MAC_PROCESS).lower() in names
    if PLATFORM == "win":
        p = subprocess.run(["tasklist", "/FO", "CSV", "/NH", "/FI", "IMAGENAME eq " + WIN_PROCESS],
                           capture_output=True, text=True)
        return WIN_PROCESS in p.stdout.lower()
    p = subprocess.run(["pgrep", "-x", MAC_PROCESS], capture_output=True, text=True)
    return p.returncode == 0


def stop():
    """End Teams: macOS asks it to quit first; then it is ended. Waits up to 30 s for it to be gone."""
    if FAKE_PS is not None:
        open(FAKE_PS, "w").close()
    elif PLATFORM == "win":
        subprocess.run(["taskkill", "/IM", WIN_PROCESS, "/T", "/F"], capture_output=True)
    else:
        subprocess.run(["osascript", "-e", 'tell application "Microsoft Teams" to quit'], capture_output=True)
        time.sleep(3)
        if running():
            subprocess.run(["pkill", "-x", MAC_PROCESS], capture_output=True)
    for _ in range(30):
        if not running():
            return True
        time.sleep(1)
    return False


def start():
    if FAKE_PS is not None:
        with open(FAKE_PS, "a", encoding="utf-8") as f:
            f.write((WIN_PROCESS if PLATFORM == "win" else MAC_PROCESS) + "\n")
        return
    if PLATFORM == "win":
        subprocess.Popen(["explorer.exe", "shell:AppsFolder\\%s!MSTeams" % WIN_PACKAGE])
    else:
        subprocess.Popen(["open", "-a", "Microsoft Teams"])


def backups(where):
    try:
        return sorted(os.path.join(where, n) for n in os.listdir(where) if n.startswith(backup_prefix()))
    except OSError:
        return []


def items(paths):
    """What moves: on Windows each entry of the cache folder but the backgrounds; on macOS each folder whole."""
    if PLATFORM != "win":
        return [p for p in paths if os.path.exists(p)]
    cache = paths[0]
    return [os.path.join(cache, n) for n in sorted(os.listdir(cache)) if n not in KEEP] if os.path.isdir(cache) else []


def cmd_check(_):
    paths, where, client = layout()
    if PLATFORM == "other":
        print("This computer is neither Windows nor macOS: Teams runs in the browser here, and a browser's own "
              "\"clear site data\" for teams.microsoft.com is the equivalent.")
        return 1
    if not os.path.isdir(client):
        print("New Teams is not installed for this user (no %s)." % client)
        return 1
    print("Teams: installed (%s), %s" % (client, "RUNNING" if running() else "not running"))
    move = items(paths)
    print("Cache: %s in %s" % (mb(sum(size(p) for p in move)), "; ".join(paths)) if move else
          "Cache: empty (%s)" % "; ".join(paths))
    if PLATFORM == "win" and os.path.isdir(os.path.join(paths[0], "Backgrounds")):
        print("Custom backgrounds: kept in place by `clear`")
    old = backups(where)
    for b in old:
        print("Earlier backup: %s (%s); the user may delete it" % (b, mb(size(b))))
    classic = os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Teams") if PLATFORM == "win" else ""
    if classic and os.path.isdir(classic):
        print("Classic Teams data is here too (%s): that client is retired, and `clear` leaves it alone" % classic)
    return 0


def cmd_clear(args):
    paths, where, client = layout()
    if PLATFORM == "other" or not os.path.isdir(client):
        print("New Teams is not installed for this user here: nothing to clear.")
        return 1
    if running():
        if not args.stop:
            print("Teams is running (its own Quit often leaves it running in the background). With the user's yes, "
                  "run this again with --stop, which ends it. Nothing was moved.")
            return 2
        if not stop():
            print("Teams is still running after 30 seconds. Nothing was moved.")
            return 2
        print("Teams: ended")
    move = items(paths)
    if not move:
        print("The cache is already empty: nothing to move.%s" % (" Starting Teams." if not args.no_start else ""))
        if not args.no_start:
            start()
        return 0
    backup = os.path.join(where, backup_prefix() + time.strftime("%Y%m%d-%H%M%S"))
    os.makedirs(backup)
    moved, failed = 0, []
    for p in move:
        target = os.path.join(backup, os.path.basename(p))
        for attempt in range(10):           # a helper process can hold a file for a few seconds after Teams ends
            try:
                os.rename(p, target)
                moved += 1
                break
            except OSError as e:
                if attempt == 9:
                    failed.append("%s (%s)" % (p, e.strerror or e))
                else:
                    time.sleep(1)
    print("Moved %d item(s) of the cache into %s" % (moved, backup))
    if failed:
        print("Could not move (in use, or not allowed): %s. Make sure Teams is fully quit and run `clear` again; "
              "what moved stays in the backup." % "; ".join(failed))
        return 1
    if not args.no_start:
        start()
        print("Teams: started. Its first start rebuilds the cache, so it is slower, and it may ask the user to sign in.")
    print("Once a message sends, the user may delete %s (nothing in it is needed)." % backup)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check", help="read-only: Teams, its cache, earlier backups")
    c = sub.add_parser("clear", help="move the cache aside (Teams quit first), then start Teams")
    c.add_argument("--stop", action="store_true", help="end a running Teams first (after the user's yes)")
    c.add_argument("--no-start", action="store_true", help="leave Teams closed afterwards")
    args = ap.parse_args(argv)
    return {"check": cmd_check, "clear": cmd_clear}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
