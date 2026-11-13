"""The runners on this machine: their state from their own log, setting up new ones, starting and stopping them."""
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time
from .util import moment
from .config import SLUG
from .system import WINDOWS, alive, apart, download, end, notify, own_command, release, write


class Runner:
    def __init__(self, cfg, n):
        self.name = cfg.local["name"] if n == 1 else f"{cfg.local['name']}-{n}"
        self.dir = cfg.local["dir"] if n == 1 else f"{cfg.local['dir']}-{n}"
        self.log = os.path.join(self.dir, "run.log")
        self.pidfile = os.path.join(self.dir, "run.pid")

    @property
    def configured(self):
        return os.path.exists(os.path.join(self.dir, ".runner"))

    def running(self):
        return alive(self.pidfile) is not None

    def start(self):
        # Installed as a service as well, the same runner would be started
        # twice: "a session is already running".
        if os.path.exists(os.path.join(self.dir, ".service")):
            subprocess.run(["./svc.sh", "stop"], cwd=self.dir, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        script = os.path.join(self.dir, "run.cmd") if WINDOWS else "./run.sh"
        with open(self.log, "wb") as log:
            process = subprocess.Popen([script], cwd=self.dir, stdin=subprocess.DEVNULL,
                                       stdout=log, stderr=subprocess.STDOUT, **apart())
        write(self.pidfile, process.pid)

    def stop(self):
        end(self.pidfile)

    def tail(self, size=16384):
        try:
            with open(self.log, "rb") as log:
                log.seek(0, os.SEEK_END)
                log.seek(max(0, log.tell() - size))
                return log.read().decode("utf-8", "replace").splitlines()[-200:]
        except OSError:
            return []

    def live(self, size=16384):
        """What the job that runs now has printed so far. GitHub gives no log of a job before it ends;
        the runner keeps each step's output in _diag/pages until then, and writes it there in blocks.
        The lines of the newest page that has any, or None where there is none."""
        try:
            pages = [page for page in glob.glob(os.path.join(self.dir, "_diag", "pages", "*.log")) if os.path.getsize(page)]
            if not pages:
                return None
            with open(max(pages, key=os.path.getmtime), "rb") as page:
                page.seek(0, os.SEEK_END)
                page.seek(max(0, page.tell() - size))
                # The last piece is a line cut by the block's end, or nothing.
                return page.read().decode("utf-8", "replace").split("\n")[:-1]
        except OSError:
            return None

    def finished(self):
        """The jobs its log says ended: (when, job, result)."""
        ended = []
        for line in self.tail():
            stamp, _, said = line.partition("Z: ")
            if said.startswith("Job ") and " completed with result: " in said:
                name, _, result = said[4:].partition(" completed with result: ")
                ended.append((stamp.strip(), name, result.strip()))
        return ended

    def state(self):
        """What the runner says it is doing, in its own words in the log:
        (state, job, since, the last job's result)."""
        if not self.configured:
            return "not set up", "", None, ""
        if not self.running():
            return "stopped", "", None, ""
        return said_by(self.tail())


def said_by(lines):
    """What a runner's log says it is doing: (state, job, since, the last
    job's result). A local run.log and a service's journal say it alike."""
    state, job, since, last = "starting", "", None, ""
    for line in lines:
        stamp, _, said = line.partition("Z: ")
        if not said:
            continue
        at = moment(stamp, "%Y-%m-%d %H:%M:%S")
        if said.startswith("Listening for Jobs"):
            state, job, since = "listening", "", at
        elif said.startswith("Running job: "):
            state, job, since = "running", said[len("Running job: "):].strip(), at
        elif said.startswith("Job ") and " completed with result: " in said:
            name, _, result = said[4:].partition(" completed with result: ")
            state, job, since, last = "listening", "", at, f"{name} {result.strip().lower()}"
    return state, job, since, last


def registration_token(cfg):
    repo = cfg.local["repo"]
    return gh_token(cfg) or input(f"A registration token (github.com/{repo} › Settings › Actions › Runners › "
                               "New self-hosted runner): ").strip()


def set_up(cfg, runner, token, quiet=False):
    """Downloads a runner into its folder and registers it. Quiet, for the
    screen: what the tools say is kept for the error, not printed over it."""
    if not quiet:
        print(f"Setting up {runner.name} in {runner.dir}")
    os.makedirs(runner.dir, exist_ok=True)
    download(release(cfg.version), runner.dir)
    config = [os.path.join(runner.dir, "config.cmd")] if WINDOWS else ["./config.sh"]
    got = subprocess.run([*config, "--url", f"https://github.com/{cfg.local['repo']}", "--token", token,
                          "--name", runner.name, "--unattended", "--replace"], cwd=runner.dir,
                         capture_output=quiet, text=True)
    if got.returncode:
        raise OSError(((got.stderr or got.stdout or "").strip()[-300:] if quiet else "") or f"config exited {got.returncode}")


TOKEN = re.compile(r"^[A-Za-z0-9_-]{10,200}$")


def add_runner(cfg, runners, token):
    """A new runner next to the others, from a registration token (or from
    `gh`, when none is given): what to say of it, and whether it went."""
    token = token.strip()
    if token and not TOKEN.match(token):
        return "That is not a registration token: letters and digits only", False
    token = token or gh_token(cfg)
    if not token:
        return "gh could not make a token: paste one from Settings › Actions › Runners › New self-hosted runner", False
    runner = Runner(cfg, len(runners) + 1)
    try:
        set_up(cfg, runner, token, quiet=True)
        runner.start()
    except (OSError, subprocess.SubprocessError) as err:
        return f"{runner.name} is not set up: {err}", False
    runners.append(runner)
    # The watcher knows the runners it started with: it begins again with this one too.
    if alive(cfg.watch):
        end(cfg.watch)
        keep_watch(cfg)
    return f"{runner.name} is up", True


def gh_token(cfg):
    """A registration token from `gh`, when it may make one (admin of the repository)."""
    if not shutil.which("gh"):
        return None
    got = subprocess.run(["gh", "api", "-X", "POST", f"repos/{cfg.local['repo']}/actions/runners/registration-token",
                          "--jq", ".token"], capture_output=True, text=True)
    return got.stdout.strip() if got.returncode == 0 and got.stdout.strip() else None


def start_all(cfg, runners):
    """Set up what is missing, unlock the keychain if there is one to unlock,
    start what is stopped."""
    missing = [runner for runner in runners if not runner.configured]
    if missing:
        token = registration_token(cfg)
        for runner in missing:
            try:
                set_up(cfg, runner, token)
            except (OSError, subprocess.CalledProcessError) as err:
                print(f"{runner.name} is not set up: {err}")
    stopped = [runner for runner in runners if runner.configured and not runner.running()]
    if stopped and cfg.keychain and shutil.which("security") and os.path.exists(cfg.keychain):
        print("The keychain, for signing:")
        if subprocess.run(["security", "unlock-keychain", cfg.keychain]).returncode:
            print("Still locked: signing fails until it is unlocked.")
    for runner in stopped:
        runner.start()
    if not alive(cfg.awake) and (shutil.which("caffeinate") or WINDOWS):
        # macOS: caffeinate. Windows: a process of its own that asks to keep
        # the system awake (ES_CONTINUOUS | ES_SYSTEM_REQUIRED) for as long as it lives.
        command = ["caffeinate", "-ims"] if not WINDOWS else [
            sys.executable, "-c",
            "import ctypes, time\nctypes.windll.kernel32.SetThreadExecutionState(0x80000001)\nwhile True: time.sleep(3600)"]
        awake = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, **apart())
        write(cfg.awake, awake.pid)
    keep_watch(cfg)


def keep_watch(cfg):
    """The watcher (--watch) beside the runners, apart from the screen as
    they are."""
    if not alive(cfg.watch):
        command, env = own_command("--watch")
        watcher = subprocess.Popen(command, env=env, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **apart())
        write(cfg.watch, watcher.pid)


def stop_all(cfg, runners):
    for runner in runners:
        runner.stop()
    end(cfg.awake)
    end(cfg.watch)


def watch(cfg, runners):
    """A notification for every job that ends, and a line for it in jobs.log,
    so a failure is heard of without watching for it. The jobs already ended
    when it starts are not news."""
    seen = {runner.name: set(runner.finished()) for runner in runners}
    while True:
        time.sleep(5)
        for runner in runners:
            for ended in runner.finished():
                if ended in seen[runner.name]:
                    continue
                seen[runner.name].add(ended)
                stamp, job, result = ended
                name = cfg.names.get(job, job)
                good = result.lower() == "succeeded"
                notify(f"runner · {runner.name}", f"{name} {result.lower()}", "Glass" if good else "Basso")
                with open(cfg.jobs, "a") as log:
                    log.write(f"{stamp}Z {runner.name} {name} {result}\n")


def runner_count(cfg):
    """The configured count, or more where more are set up on disk: a runner
    made from the screen is not in the config."""
    count = cfg.local["count"]
    while Runner(cfg, count + 1).configured:
        count += 1
    return count



# Folders the scan does not enter: macOS asks the user's permission for some of
# them, and the rest hold things that are never a runner.
SKIP = {"Library", "Documents", "Desktop", "Downloads", "Pictures", "Movies", "Music", "Applications", "AppData",
        "node_modules", "target", "site-packages", "venv", ".git", ".cache", ".cargo", ".rustup", ".npm", ".Trash"}


def find_runners(home=None, depth=3, limit=3000):
    """The runners already set up on this machine: the folders that hold the
    `.runner` file a runner writes when it is registered. Looks in the usual
    places and walks the home folder a few levels down. [{dir, name, repo}]"""
    home = home or os.path.expanduser("~")
    places = set(glob.glob(os.path.join(home, "actions-runner*")))
    places |= set(glob.glob("/opt/actions-runner*")) | set(glob.glob("C:\\actions-runner*"))
    seen = 0
    todo = [(home, 0)]
    while todo and seen < limit:
        folder, level = todo.pop()
        seen += 1
        try:
            entries = list(os.scandir(folder))
        except OSError:
            continue
        for entry in entries:
            try:
                if entry.is_dir(follow_symlinks=False) and entry.name not in SKIP and level < depth:
                    todo.append((entry.path, level + 1))
                elif entry.name == ".runner" and entry.is_file(follow_symlinks=False):
                    places.add(folder)
            except OSError:
                continue
    found = []
    for folder in sorted(places):
        try:
            with open(os.path.join(folder, ".runner"), encoding="utf-8-sig") as file:
                info = json.load(file)
        except (OSError, ValueError):
            continue
        if not isinstance(info, dict):
            continue
        url = str(info.get("gitHubUrl", ""))
        repo = url.split("github.com/", 1)[-1].strip("/") if "github.com/" in url else ""
        name = info.get("agentName")
        found.append({"dir": folder, "name": name if isinstance(name, str) else os.path.basename(folder),
                      "repo": repo if SLUG.match(repo) else ""})
    return found


def plan_of(found, home=None):
    """What the config can say of runners that were found: a name and a folder
    with -2, -3 after them, and how many. None if they are not in such a row.
    The rest are left over: the config cannot hold them."""
    home = home or os.path.expanduser("~")
    by_dir = {item["dir"]: item for item in found}
    # Try every folder as the start of a row, and keep the longest.
    best = None
    for item in found:
        count = 1
        while f"{item['dir']}-{count + 1}" in by_dir and by_dir[f"{item['dir']}-{count + 1}"]["name"] == f"{item['name']}-{count + 1}":
            count += 1
        if best is None or count > best[0]:
            best = (count, item)
    if not best:
        return None, []
    count, item = best
    row = {item["dir"]} | {f"{item['dir']}-{k}" for k in range(2, count + 1)}
    shown = item["dir"]
    if shown.startswith(home + os.sep):
        shown = "~" + shown[len(home):]
    return ({"name": item["name"], "dir": shown, "count": count, "repo": item["repo"]},
            [other for other in found if other["dir"] not in row])
