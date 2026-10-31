"""Builds that do not go through GitHub: `runnerdeck run` records them, the screen reads them."""
import json
import os
import platform
import shlex
import subprocess
import sys
import threading
import time
from .util import clean

# How many records are kept, and for how many seconds a build that nobody touched is still called running.
KEEP = 60
FRESH = 90


def data_dir():
    """Where the records are: RUNNERDECK_DATA, else ~/.local/share/runnerdeck (on Windows %LOCALAPPDATA%)."""
    chosen = os.environ.get("RUNNERDECK_DATA")
    if chosen:
        return os.path.expanduser(chosen)
    if os.name == "nt":
        return os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "runnerdeck")
    return os.path.expanduser("~/.local/share/runnerdeck")


def folder(root=None):
    return os.path.join(root or data_dir(), "builds")


def normalize(info, mtime, now):
    """One record as the screen needs it, or None if it is not one. `mtime` is when the file was
    last touched: a build that has not ended and has been quiet too long was interrupted."""
    if not isinstance(info, dict) or not isinstance(info.get("name"), str):
        return None

    def number(value):
        return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None

    def text(key, size=200):
        value = info.get(key)
        return clean(value)[:size] if isinstance(value, str) else ""

    start, end, code = number(info.get("start")), number(info.get("end")), info.get("code")
    code = code if isinstance(code, int) and not isinstance(code, bool) else None
    if end is not None:
        status = "success" if code == 0 else "cancelled" if code in (130, 143) else "failure"
    else:
        status = "running" if now - mtime < FRESH else "interrupted"
    return {"id": text("id", 60), "name": text("name", 60), "cmd": text("cmd"), "cwd": text("cwd"),
            "branch": text("branch", 60), "sha": text("sha", 12), "host": text("host", 40),
            "start": start, "end": end, "code": code, "status": status}


def recent(limit=10, root=None):
    """The latest records of this machine, newest first."""
    directory = folder(root)
    files = []
    try:
        for name in os.listdir(directory):
            if name.endswith(".json"):
                try:
                    files.append((os.stat(os.path.join(directory, name)).st_mtime, os.path.join(directory, name)))
                except OSError:
                    continue
    except OSError:
        return []
    now, found = time.time(), []
    for mtime, path in sorted(files, reverse=True)[:limit]:
        try:
            with open(path, encoding="utf-8") as file:
                item = normalize(json.load(file), mtime, now)
        except (OSError, ValueError):
            continue
        if item:
            found.append(item)
    return found


def default_name(argv):
    """A name from the command: its program, and the word after it if that is a short plain one (cargo test)."""
    first = os.path.basename(argv[0])
    second = argv[1] if len(argv) > 1 and not argv[1].startswith("-") and "/" not in argv[1] and len(argv[1]) <= 20 else ""
    return f"{first} {second}".strip()


def git(cwd, *args):
    try:
        got = subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True, timeout=2)
        return got.stdout.strip() if got.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def write(path, info):
    """The record, all at once: a reader never sees half of it."""
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8") as file:
        json.dump(info, file)
    os.replace(temporary, path)


def record(argv, name=None, root=None, beat=20.0):
    """Runs a command as it is, with its own input and output, and keeps a record of it: when it began,
    how it ended and how long it took. While it runs the record is touched every `beat` seconds, so
    that a build that was killed is not shown as running for ever. Returns the command's exit code."""
    directory = folder(root)
    os.makedirs(directory, exist_ok=True)
    started = time.time()
    cwd = os.getcwd()
    ident = f"{int(started * 1000)}-{os.getpid()}"
    path = os.path.join(directory, ident + ".json")
    info = {"id": ident, "name": name or default_name(argv), "cmd": " ".join(shlex.quote(part) for part in argv),
            "cwd": cwd, "branch": git(cwd, "rev-parse", "--abbrev-ref", "HEAD"), "sha": git(cwd, "rev-parse", "--short", "HEAD"),
            "host": platform.node().split(".")[0], "start": started, "end": None, "code": None}
    write(path, info)
    stop = threading.Event()

    def touch():
        while not stop.wait(beat):
            try:
                os.utime(path)
            except OSError:
                return
    threading.Thread(target=touch, daemon=True).start()
    code = 1
    try:
        try:
            process = subprocess.Popen(argv)
            try:
                code = process.wait()
            except KeyboardInterrupt:
                # The child got the same Ctrl-C: wait for it to end, and say that it was stopped.
                process.wait()
                code = 130
        except FileNotFoundError:
            print(f"runnerdeck: {argv[0]}: command not found", file=sys.stderr)
            code = 127
        except PermissionError:
            print(f"runnerdeck: {argv[0]}: not allowed to run", file=sys.stderr)
            code = 126
        if code < 0:
            code = 128 - code
    finally:
        stop.set()
        info["end"], info["code"] = time.time(), code
        write(path, info)
        prune(directory)
    return code


def prune(directory):
    """Only the latest KEEP records stay."""
    try:
        files = sorted((os.stat(os.path.join(directory, n)).st_mtime, n) for n in os.listdir(directory) if n.endswith(".json"))
        for _, name in files[:-KEEP]:
            os.remove(os.path.join(directory, name))
    except OSError:
        pass


def run_recorded(args):
    """`runnerdeck run [--name NAME] -- command ...`: the exit code to leave with."""
    name = None
    if args[:1] == ["--name"] and len(args) > 1:
        name, args = args[1], args[2:]
    if args[:1] == ["--"]:
        args = args[1:]
    if not args:
        print("usage: runnerdeck run [--name NAME] -- command [arguments]", file=sys.stderr)
        return 2
    return record(args, name)
