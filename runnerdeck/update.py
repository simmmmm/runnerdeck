"""Bringing runnerdeck itself up to date, from the clone it was installed from: a fast-forward of main and nothing else."""
import os
import subprocess
import sys

from .config import default_path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# What `--install` made: the command opens this one file, a copy of the code as it was then.
PYZ = os.path.expanduser("~/runnerdeck.pyz")


def source_file():
    return os.path.join(os.path.dirname(default_path()), "source")


def remember():
    """When installed from a clone: which one, so that the installed copy can update itself later."""
    if os.path.isdir(os.path.join(ROOT, ".git")):
        os.makedirs(os.path.dirname(source_file()), exist_ok=True)
        with open(source_file(), "w") as file:
            file.write(ROOT + "\n")


def clone_dir():
    """The clone to update: the one this runs from, or the one that this was installed from; or ''."""
    if os.path.isdir(os.path.join(ROOT, ".git")):
        return ROOT
    try:
        with open(source_file()) as file:
            path = file.read().strip()
    except OSError:
        return ""
    return path if path and os.path.isdir(os.path.join(path, ".git")) else ""


def git(clone, *args):
    got = subprocess.run(["git", "-C", clone, *args], capture_output=True, text=True, timeout=60)
    return got.returncode, got.stdout.strip(), got.stderr.strip()


def behind():
    """Whether main of origin is ahead of the clone: only asked, nothing is changed. A clone with commits of its
    own that is ahead of main is not behind."""
    clone = clone_dir()
    if not clone:
        return False
    try:
        code, listed, _ = git(clone, "ls-remote", "origin", "main")
        remote = listed.split()[0] if code == 0 and listed else ""
        if not remote:
            return False
        here = git(clone, "rev-parse", "HEAD")[1]
        # Behind when the remote commit is neither the clone's own nor one that the clone already has.
        return remote != here and git(clone, "merge-base", "--is-ancestor", remote, "HEAD")[0] != 0
    except (OSError, subprocess.SubprocessError):
        return False


def rebuild(clone):
    """The installed copy made again from the clone, as it is now. Built beside it and put in its place in one
    step, so that a copy that is running is not cut under its own feet."""
    new = PYZ + ".new"
    got = subprocess.run([sys.executable, "-m", "runnerdeck", "--build", new], cwd=clone, capture_output=True, text=True,
                         timeout=120, env=dict(os.environ, PYTHONPATH=clone))
    if got.returncode:
        return False
    os.replace(new, PYZ)
    return True


def update():
    """(did it go, what to say). Only a clone that is on main with nothing changed is moved, and only forward:
    a change of a person's own is never lost, and the runners, which are other programs, are not touched."""
    clone = clone_dir()
    if not clone:
        return False, ("There is no clone to update from. Go to the clone and run: python3 -m runnerdeck --install\n"
                       "That also tells the installed copy where it is.")
    code, branch, _ = git(clone, "rev-parse", "--abbrev-ref", "HEAD")
    if code or branch != "main":
        return False, f"The clone ({clone}) is on {branch or 'no branch'}, not on main: nothing changed"
    if git(clone, "status", "--porcelain", "--untracked-files=no")[1]:
        return False, f"The clone ({clone}) has changes of your own: nothing changed. Save them first (git stash)."
    before = git(clone, "rev-parse", "--short", "HEAD")[1]
    code, _, error = git(clone, "fetch", "origin", "main")
    if code:
        return False, f"Could not fetch: {error.splitlines()[-1] if error else 'git said no'}"
    code, _, error = git(clone, "merge", "--ff-only", "FETCH_HEAD")
    if code:
        return False, "The clone is not behind main but apart from it: nothing changed. Run git status."
    after = git(clone, "rev-parse", "--short", "HEAD")[1]
    # The command `runnerdeck` opens a copy that was made at the install: it is made again, also when the clone
    # was newer than it already.
    copy = ""
    if os.path.exists(PYZ):
        copy = " The command runnerdeck is up to date too." if rebuild(clone) else " The command runnerdeck could not be rebuilt: run python3 -m runnerdeck --install."
    if after == before:
        return True, f"Already the newest ({after}).{copy}"
    return True, f"Updated {before} → {after}.{copy} Start runnerdeck again to use it. Your runners were not touched."
