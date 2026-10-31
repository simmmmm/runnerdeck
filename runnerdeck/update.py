"""Bringing runnerdeck itself up to date, from the clone it runs from: a fast-forward of main and nothing else."""
import os
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def git(*args):
    got = subprocess.run(["git", "-C", ROOT, *args], capture_output=True, text=True, timeout=60)
    return got.returncode, got.stdout.strip(), got.stderr.strip()


def update():
    """(did it go, what to say). Only a clone that is on main with nothing changed is moved, and only forward:
    a change of a person's own is never lost, and the runners, which are other programs, are not touched."""
    if not os.path.isdir(os.path.join(ROOT, ".git")):
        return False, "This is not a clone, so it cannot update itself. Get the new version the way you got this one."
    code, branch, _ = git("rev-parse", "--abbrev-ref", "HEAD")
    if code or branch != "main":
        return False, f"The clone is on {branch or 'no branch'}, not on main: nothing changed"
    if git("status", "--porcelain", "--untracked-files=no")[1]:
        return False, "The clone has changes of your own: nothing changed. Save them first (git stash)."
    before = git("rev-parse", "--short", "HEAD")[1]
    code, _, error = git("fetch", "origin", "main")
    if code:
        return False, f"Could not fetch: {error.splitlines()[-1] if error else 'git said no'}"
    code, _, error = git("merge", "--ff-only", "FETCH_HEAD")
    if code:
        return False, "The clone is not behind main but apart from it: nothing changed. Run git status."
    after = git("rev-parse", "--short", "HEAD")[1]
    if after == before:
        return True, f"Already the newest ({after})."
    return True, f"Updated {before} → {after}. Start runnerdeck again to use it. Your runners were not touched."
