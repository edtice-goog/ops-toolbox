# ops-toolbox

Small, self-contained scripts kept for future reference. Each file starts with a comment saying what it does,
how to run it, and what it was tested on.

## foreman/ — service-account work from the Foreman Rails console

Written for replacing a shared service account with a per-consumer clone on Foreman 3.5 (Ubuntu 20.04), where
`hammer` was not usable. Everything runs through `foreman-rake console`, fed a script on stdin.

| Script | What it does | Changes anything? |
|---|---|---|
| `user-report.rb` | Auth source, admin flag (own / via groups), roles, groups, orgs/locations of chosen users; all service-style accounts; auth sources; failed-login limit; hosts per hostgroup root | No |
| `clone-user.rb` | Creates a user with the effective permissions of another (Internal auth, hidden password prompt, all-or-nothing save) | Creates one user |
| `compare-users.rb` | Proves two users have the same effective permissions (admin, taxonomies, every permission, visible object counts) | No |
| `check-password.rb` | Tells whether a typed password matches the stored hash, without an API login | No |
| `api-probe.sh` | GETs a few API endpoints as one user and prints status + visible counts | No (GET only) |

Typical sequence: `user-report.rb` → `clone-user.rb` → `compare-users.rb` (expect `SAME:`) → `api-probe.sh` from
the machine that will use the account → point that one consumer at the new account.

Lessons from doing this on Foreman 3.5:

- **Run the console as the `foreman` user** (`sudo -u foreman ... foreman-rake console`). Plain `sudo foreman-rake`
  switches user with `su -c`, which starts a new session with no controlling terminal, so a hidden password
  prompt (`IO.console.getpass`) has nothing to read from. Use `ssh -t`.
- **Check the source account's organizations and locations**, not just its roles: an account with roles but no
  taxonomy logs in fine and sees nothing, which looks exactly like "the service account doesn't work".
- **Admin can come from a user group.** `user.admin` can be false while the account is effectively admin through
  a group; `cached_usergroups.any?(&:admin)` tells the truth.
- **`failed_login_attempts_limit` is per source address.** One client on a host with a stale password can get the
  host blocked, so clients with *correct* credentials on the same host fail too.
- **In our case `last_login_on` did not move for REST API calls with basic auth**, so it is no evidence of whether an account
  is in use.
- `/api/v2/users/current` returns 404 on 3.5; `/api/v2/hosts?per_page=1` is a reliable "does this login work" probe.

`user-report.rb`, `clone-user.rb`, `compare-users.rb` and `api-probe.sh` were used in production with the account
names hardcoded; the environment-variable parameters here were added afterwards. `check-password.rb` has only been
syntax-checked.

## claude-code-transcripts/ — sharing a Claude Code session with someone who was not there

The desktop app's session Export gives a `.jsonl` transcript that is complete but unreadable, and it can contain
secrets that surfaced in tool output.

| Script | What it does |
|---|---|
| `redact.py` | Replaces secrets (from a file you build, values never printed) and password hashes in an unpacked export; verifies nothing is left |
| `scan_secrets.py` | Masked second-opinion scan for anything still credential-shaped |
| `render_conversation.py` | Turns the transcript into a readable Markdown conversation: messages and replies in full, one line per stretch of tool calls, blocked calls noted, git remote operations shown in full |
| `conversation.css` | Styling for the pandoc HTML output |

```bash
python redact.py export-copy/ secrets.txt
python scan_secrets.py export-copy/
python render_conversation.py export-copy/transcript.jsonl conversation.md --title "..." --user-name Ed --intro-file intro.md
pandoc conversation.md -t html5 --standalone --embed-resources --css conversation.css -o conversation.html
pandoc conversation.md -t docx -o conversation.docx
```

## License

MIT, see `LICENSE`.
