"""Builds that do not go through GitHub: `runnerdeck run` records them, the screen reads them."""
import glob
import json
import os
import platform
import re
import shlex
import subprocess
import sys
import threading
import time
from .util import STAMP, clean

# How many records are kept, and for how many seconds a build that nobody touched is still called running.
KEEP = 60
FRESH = 90
# A build's row on the RUNS page: a number no run's, request's or issue's can be.
BUILD_ROW = 10**15


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
            "branch": text("branch", 60), "sha": text("sha", 12), "host": text("host", 40), "toolchain": text("toolchain", 60),
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
            # What it printed, where that was kept (see `record`).
            item["log"] = path[:-5] + ".log"
            found.append(item)
    return found


def as_runs(limit=5, root=None):
    """The latest builds in the shape of GitHub's runs, for the RUNS page: a name, a branch, a commit, how
    it ended and when it began. The build itself is under "build"."""
    shaped = []
    for build in recent(limit, root):
        going = build["status"] == "running"
        shaped.append({"row": BUILD_ROW + int((build["start"] or 0) * 1000), "build": build, "repo": "",
                       "workflowName": build["name"], "headBranch": build["branch"], "headSha": build["sha"],
                       "status": "in_progress" if going else "completed",
                       "conclusion": "" if going else {"interrupted": "cancelled"}.get(build["status"], build["status"]),
                       "createdAt": time.strftime(STAMP, time.gmtime(build["start"] or 0))})
    return shaped


def printed(build, size=16384):
    """The end of what a build printed, as lines; None where nothing of it was kept."""
    try:
        with open(build.get("log") or "", "rb") as log:
            log.seek(0, os.SEEK_END)
            log.seek(max(0, log.tell() - size))
            return log.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return None


def read_text(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as file:
            return file.read()
    except OSError:
        return ""


def rust_toolchain(cwd, argv=(), timeout=3.0):
    """The Rust toolchain that a build here would use, as "rustc 1.82.0 stable", or "" if this is not a Rust
    folder. Rustup's own rules, read from its files: +toolchain on the command, RUSTUP_TOOLCHAIN, an override
    of this folder, a rust-toolchain(.toml) file, the default. Not by running `rustc`: in a folder whose
    file names a toolchain that is not installed, rustup would download it, and a log must install nothing.
    The compiler of the toolchain's own folder is run directly instead, which never downloads."""
    folders, here = [], os.path.abspath(cwd)
    for _ in range(8):
        folders.append(here)
        parent = os.path.dirname(here)
        if parent == here:
            break
        here = parent
    file_choice = ""
    for folder in folders:
        for name in ("rust-toolchain.toml", "rust-toolchain"):
            body = read_text(os.path.join(folder, name))
            found = re.search(r'channel\s*=\s*"([^"]+)"', body) or (
                None if "=" in body or not body.strip() else re.match(r"\s*([^\s#]+)", body))
            if found and not file_choice:
                file_choice = found.group(1)
    if not file_choice and not any(os.path.exists(os.path.join(folder, "Cargo.toml")) for folder in folders):
        return ""
    home = os.environ.get("RUSTUP_HOME") or os.path.expanduser("~/.rustup")
    settings = read_text(os.path.join(home, "settings.toml"))
    default = (re.search(r'^default_toolchain\s*=\s*"([^"]+)"', settings, re.M) or [None, ""])[1]
    override, best = "", -1
    for path, chosen in re.findall(r'^"([^"]+)"\s*=\s*"([^"]+)"', settings.split("[overrides]")[-1], re.M) if "[overrides]" in settings else []:
        if (os.path.abspath(cwd) == path or os.path.abspath(cwd).startswith(path.rstrip(os.sep) + os.sep)) and len(path) > best:
            override, best = chosen, len(path)
    wanted = (argv[1][1:] if len(argv) > 1 and argv[1].startswith("+") and os.path.basename(argv[0]) in
              ("cargo", "rustc", "rustdoc", "rustfmt", "cargo-clippy") else "")
    wanted = wanted or os.environ.get("RUSTUP_TOOLCHAIN") or override or file_choice or default
    root = os.path.join(home, "toolchains")
    if not os.path.isdir(root):
        # No rustup: whatever rustc there is on the PATH (a distribution's own, or none).
        compiler, label = "rustc", ""
    else:
        if not wanted:
            return ""
        matches = sorted(name for name in os.listdir(root) if name == wanted or name.startswith(wanted + "-"))
        if not matches:
            return f"{wanted} (not installed)"
        compiler, label = os.path.join(root, matches[0], "bin", "rustc"), re.sub(
            r"-(x86_64|aarch64|i686|i586|armv7|arm|riscv64gc|powerpc64le|s390x|loongarch64)[A-Za-z0-9_.-]*$", "", matches[0])
    try:
        said = subprocess.run([compiler, "--version"], capture_output=True, text=True, timeout=timeout).stdout.split()
    except (OSError, subprocess.SubprocessError):
        return label
    version = " ".join(said[:2]) if len(said) >= 2 and said[0] == "rustc" else ""
    if label and version.endswith(" " + label):
        label = ""                              # a toolchain that is only a version: it is said once
    return f"{version} {label}".strip()


# What can tell which tools a build used: each takes the folder and the command and gives a short text, or "".
# Add one for another language here (Go, Node, Python ...) and it is recorded and shown the same way.
DETECTORS = (rust_toolchain,)


def toolchain(cwd, argv):
    for detect in DETECTORS:
        try:
            found = detect(cwd, argv)
        except Exception:
            found = ""
        if found:
            return found
    return ""


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


def copy(source, target, log):
    """What the command prints goes where it would have gone, at once, and into the build's log as well."""
    while True:
        try:
            data = os.read(source.fileno(), 65536)
        except OSError:
            return
        if not data:
            return
        for to in (target, log):
            try:
                to.write(data)
                to.flush()
            except (OSError, ValueError):
                pass


def record(argv, name=None, root=None, beat=20.0):
    """Runs a command as it is, with its own input and output, and keeps a record of it: when it began,
    how it ended and how long it took. While it runs the record is touched every `beat` seconds, so
    that a build that was killed is not shown as running for ever. Returns the command's exit code.
    What it prints is kept beside the record, for the screen to show while it runs, where it does not
    print to a terminal: a person at a terminal reads it there, and a command that is piped there
    would lose its colours and its progress bar."""
    # ponytail: no log of a build started at a terminal; a pty would give one, if that is ever missed.
    directory = folder(root)
    os.makedirs(directory, exist_ok=True)
    started = time.time()
    cwd = os.getcwd()
    ident = f"{int(started * 1000)}-{os.getpid()}"
    path = os.path.join(directory, ident + ".json")
    info = {"id": ident, "name": name or default_name(argv), "cmd": " ".join(shlex.quote(part) for part in argv),
            "cwd": cwd, "branch": git(cwd, "rev-parse", "--abbrev-ref", "HEAD"), "sha": git(cwd, "rev-parse", "--short", "HEAD"),
            "host": platform.node().split(".")[0], "toolchain": toolchain(cwd, argv),
            "start": started, "end": None, "code": None}
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
    targets = {stream: getattr(sys, stream).buffer for stream in ("stdout", "stderr")
               if hasattr(getattr(sys, stream), "buffer") and not getattr(sys, stream).isatty()}
    try:
        log = open(path[:-5] + ".log", "ab", buffering=0) if targets else None
    except OSError:
        log, targets = None, {}
    try:
        try:
            process = subprocess.Popen(argv, **{stream: subprocess.PIPE for stream in targets})
            copies = [threading.Thread(target=copy, args=(getattr(process, stream), target, log), daemon=True)
                      for stream, target in targets.items()]
            for thread in copies:
                thread.start()
            try:
                code = process.wait()
            except KeyboardInterrupt:
                # The child got the same Ctrl-C: wait for it to end, and say that it was stopped.
                process.wait()
                code = 130
            # Not for ever: something the command left running may still hold its output open.
            for thread in copies:
                thread.join(2)
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
            if os.path.exists(os.path.join(directory, name[:-5] + ".log")):
                os.remove(os.path.join(directory, name[:-5] + ".log"))
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
