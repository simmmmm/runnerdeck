#!/usr/bin/env python3
"""runnerdeck: self-hosted GitHub Actions runners, the machines they run on and
the runs they work on, on one btop-style screen in the terminal.

    runnerdeck.py --init      write an example config, then edit it
    runnerdeck.py             start the local runners that are not running, then the screen
    runnerdeck.py --status    the screen once, as text
    runnerdeck.py --install   copy this to ~/runnerdeck.py, and `runnerdeck` in your shell

What it shows: this machine (CPU, GPU, memory, power, heat; macOS or Linux),
other machines over ssh, the runners on this machine (what each is doing and how
far its job is), the last runs of your repositories, and the log of one runner.
↑ and ↓ go over the runs; c cancels one, r runs it again, o opens it. What
cannot be taken back asks first, in a box in the middle.

Add a repository, say what runners it has, and that is all: a config file
(~/.config/runnerdeck/config.ini, or RUNNERDECK_CONFIG), see --init.

    [deck]
    repos = owner/name, owner/other        # what `gh` reads runs from

    [local]                                # runners on this machine (optional)
    name = box                             # box, box-2, box-3
    dir = ~/actions-runner                 # ~/actions-runner, -2, -3
    count = 3
    version = 2.338.2                      # a new runner's first; each updates itself
    keychain = ~/Library/Keychains/login.keychain-db   # macOS: unlocked before they start

    [host pc]                              # another machine, read-only, over ssh
    ssh = user@host                        # key login: BatchMode, never a password
    service = actions-runner.service       # its runner, a systemd user service

    [approval]                             # workflows only a person may start
    workflows = Deploy                     # an issue "Deploy: <branch> <sha>" ...
    label = deploy-request                 # ... with this label stands on the screen as waiting

Nothing here starts an approval workflow by itself: an issue only asks; a or
enter in the screen starts it, after a question, from that branch if it is
still at that commit, and closes the issue.

Local runners run apart from the screen, in sessions of their own, so leaving it
(q) or losing the SSH connection leaves them running; x stops them. A watcher
(--watch) beside them notifies for every job that ends (osascript, or
notify-send) and writes it to jobs.log in the first runner's folder.

Python 3.9 and its standard library only: copy the one file anywhere.
"""
import calendar
import configparser
import ctypes
import curses
import json
import locale
import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from collections import deque

CONFIG = os.path.expanduser(os.environ.get("RUNNERDECK_CONFIG", "~/.config/runnerdeck/config.ini"))
SLUG = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
WORD = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]*$")
HOST = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@:-]*$")
EXAMPLE = """\
[deck]
repos = owner/name

# Runners on this machine, started and stopped from the screen. Leave the
# section out to only watch.
[local]
name = box
dir = ~/actions-runner
count = 1
version = 2.338.2
# keychain = ~/Library/Keychains/login.keychain-db

# Another machine, over ssh (a key, no password). Leave out if there is none.
# [host pc]
# ssh = user@host
# service = actions-runner.service

# Workflows that only you may start: an issue titled "Deploy: <branch> <sha>"
# with the label asks for one, and waits on the screen.
# [approval]
# workflows = Deploy
# label = deploy-request
"""

# Set by configure(): the repositories, where the local runners live, the other
# machines, and the workflows that wait for a person.
REPOS = []
HOME = os.path.expanduser("~")
LOCAL = None
HOSTS = []
APPROVAL = {"workflows": [], "label": ""}
ASKED = None
NAMES = {}
VERSION = "2.338.2"
KEYCHAIN = ""
AWAKE = WATCH = JOBS = ""


class ConfigError(Exception):
    pass


def configure(config):
    """Reads and checks a ConfigParser. Everything that later reaches `gh`, ssh
    or a file name has to look like what it is here."""
    global REPOS, HOME, LOCAL, HOSTS, APPROVAL, ASKED, NAMES, VERSION, KEYCHAIN, AWAKE, WATCH, JOBS

    def listed(text):
        return [word.strip() for word in text.split(",") if word.strip()]

    REPOS = listed(config.get("deck", "repos", fallback=""))
    if not REPOS:
        raise ConfigError("[deck] repos is empty: repos = owner/name")
    for repo in REPOS:
        if not SLUG.match(repo):
            raise ConfigError(f"not a repository, owner/name: {repo}")
    HOME = os.path.expanduser(os.environ.get("RUNNERDECK_HOME", "~"))
    LOCAL = None
    if config.has_section("local"):
        local = config["local"]
        LOCAL = {"name": local.get("name", "box"), "dir": os.path.expanduser(local.get("dir", "~/actions-runner")),
                 "count": int(local.get("count", "1")), "repo": local.get("repo", REPOS[0])}
        if not WORD.match(LOCAL["name"]) or " " in LOCAL["name"]:
            raise ConfigError(f"not a runner name: {LOCAL['name']}")
        if LOCAL["repo"] not in REPOS:
            raise ConfigError(f"[local] repo {LOCAL['repo']} is not in [deck] repos")
        VERSION = local.get("version", VERSION)
        KEYCHAIN = os.path.expanduser(local.get("keychain", ""))
    HOSTS = []
    for section in config.sections():
        if section.startswith("host "):
            name, host = section[5:].strip(), config[section].get("ssh", "")
            service = config[section].get("service", "")
            if not WORD.match(name) or not HOST.match(host) or (service and not HOST.match(service)):
                raise ConfigError(f"[{section}]: a name, ssh = user@host, service = name.service")
            HOSTS.append({"name": name, "ssh": host, "service": service})
    workflows = listed(config.get("approval", "workflows", fallback=""))
    label = config.get("approval", "label", fallback="").strip()
    if workflows and (not label or not WORD.match(label) or not all(WORD.match(name) for name in workflows)):
        raise ConfigError("[approval] workflows = Name, Name and a label = name")
    APPROVAL = {"workflows": workflows, "label": label}
    # "Deploy: <branch> <sha>": nothing from an issue but a workflow's name,
    # a branch's name and a commit reaches `gh`.
    ASKED = (re.compile(r"^(%s): ([A-Za-z0-9][A-Za-z0-9._/-]*) ([0-9a-f]{7,40})$"
                        % "|".join(re.escape(name) for name in workflows)) if workflows else None)
    # A job by its workflow's name: the runner's log says only the job's own.
    NAMES = dict(config["names"]) if config.has_section("names") else {}
    first = os.path.join(LOCAL["dir"] if LOCAL else os.path.join(HOME, "actions-runner"), "")
    AWAKE, WATCH, JOBS = (first + name for name in ("caffeinate.pid", "watch.pid", "jobs.log"))


def load():
    config = configparser.ConfigParser()
    if not config.read(CONFIG):
        raise ConfigError(f"no config at {CONFIG}: runnerdeck.py --init writes an example")
    configure(config)


def alive(pidfile):
    """The process a pid file names, while it runs."""
    # ponytail: a pid the system has given to something else since reads as
    # alive; a check of the command line if that is ever seen.
    try:
        with open(pidfile) as file:
            pid = int(file.read().strip())
        os.kill(pid, 0)
        return pid
    except (OSError, ValueError):
        return None


def write(pidfile, pid):
    with open(pidfile, "w") as file:
        file.write(f"{pid}\n")


def end(pidfile):
    """The process and everything it started: it was a session's leader."""
    pid = alive(pidfile)
    if pid:
        try:
            os.killpg(pid, signal.SIGTERM)
        except OSError:
            pass
    try:
        os.remove(pidfile)
    except OSError:
        pass


STAMP = "%Y-%m-%dT%H:%M:%SZ"


def moment(text, form):
    try:
        return calendar.timegm(time.strptime(text.strip(), form))
    except ValueError:
        return None


def ago(at):
    if at is None:
        return ""
    minutes = max(0, int(time.time() - at) // 60)
    if minutes < 1:
        return "now"
    if minutes < 60:
        return f"{minutes} min"
    return f"{minutes // 60} h {minutes % 60} min"


class Runner:
    def __init__(self, n):
        self.name = LOCAL["name"] if n == 1 else f"{LOCAL['name']}-{n}"
        self.dir = LOCAL["dir"] if n == 1 else f"{LOCAL['dir']}-{n}"
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
        with open(self.log, "wb") as log:
            process = subprocess.Popen(["./run.sh"], cwd=self.dir, stdin=subprocess.DEVNULL,
                                       stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
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


def asked(issue, repo="", index=0):
    """The request an issue makes, if its title is one: nothing from it but
    a workflow's name, a branch's name and a commit reaches `gh`. Its row is
    a negative number no run's can be, and none of another repository's."""
    found = ASKED.match(issue.get("title", "").strip()) if ASKED else None
    if not found:
        return None
    return {"number": issue["number"], "repo": repo, "row": -(index * 10**6 + issue["number"]), "workflow": found[1],
            "branch": found[2], "sha": found[3], "note": (issue.get("body") or "").split("\n")[0]}


def still_at(repo, branch, sha):
    """Whether the branch is still at the commit that was asked for: a
    workflow starts from a branch's head, and the head is what gets shipped."""
    got = subprocess.run(["gh", "api", f"repos/{repo}/branches/{branch}", "-q", ".commit.sha"],
                         capture_output=True, text=True, timeout=15)
    return got.returncode == 0 and got.stdout.strip().startswith(sha)


def act_on_run(run, key):
    """c, r or o on a run of GitHub's; what to say of it, and whether it went."""
    number, name = str(run["databaseId"]), run.get("workflowName", "the run")
    command = {"c": ["cancel", number], "r": ["rerun", number], "o": ["view", number, "--web"]}[key]
    got = subprocess.run(["gh", "run", *command, "--repo", run["repo"]], capture_output=True, text=True, timeout=15)
    if got.returncode:
        return f"{name}: {got.stderr.strip() or 'gh said no'}", False
    return {"c": f"{name} is being cancelled", "r": f"{name} runs again", "o": f"{name} opened"}[key], True


def row_of(item):
    """A row of the screen by what it is, as it moves: a run's number, a
    request's as a negative one."""
    return item["row"] if "row" in item else item["databaseId"]


def approve(request):
    """Starts the workflow asked for; what to say of it, and whether the
    request is over."""
    repo, workflow, branch, sha = request["repo"], request["workflow"], request["branch"], request["sha"]
    if not still_at(repo, branch, sha):
        return f"{branch} is no longer at {sha[:7]}: nothing started", False
    # One each: a run started by hand, or the list of requests lagging behind
    # a close, and a key pressed again queued the same commit again.
    runs = subprocess.run(["gh", "run", "list", "--repo", repo, "--workflow", workflow, "--branch", branch,
                           "--limit", "10", "--json", "status,headSha"], capture_output=True, text=True, timeout=15)
    try:
        listed = json.loads(runs.stdout) if runs.returncode == 0 else None
    except ValueError:
        listed = None
    if listed is None:
        return "GitHub did not say what is running: nothing started", False
    if any(run["headSha"].startswith(sha) and run["status"] != "completed" for run in listed):
        close(request, f"A {workflow} of this commit is already on its way.")
        return f"{sha[:7]} is already on its way: nothing started", True
    started = subprocess.run(["gh", "workflow", "run", workflow, "--repo", repo, "--ref", branch],
                             capture_output=True, text=True, timeout=15)
    if started.returncode:
        return f"{workflow} did not start: {started.stderr.strip()}", False
    close(request, f"Approved in runnerdeck; {workflow} started.")
    return f"{workflow} started from {branch} at {sha[:7]}", True


def close(request, words):
    subprocess.run(["gh", "issue", "close", str(request["number"]), "--repo", request["repo"], "--comment", words],
                   capture_output=True, text=True, timeout=15)


class Queue:
    """GitHub's last runs of every repository, every 20 seconds, while `gh` can
    say; and for each runner busy with one, how far its job is — the steps
    GitHub counts, and the time the last good run of that workflow took."""

    def __init__(self, once=False):
        self.runs = None
        self.jobs = {}
        self.requests = []
        # A thing being done, by its row (`row_of`), and what the row says
        # meanwhile; requests over (repository, issue), which GitHub's list may
        # still show; and what the last one came to, for the foot.
        self.working = {}
        self.over = set()
        self.said = ""
        if not shutil.which("gh") or not REPOS:
            return
        if once:
            self.fetch()
        else:
            threading.Thread(target=self.loop, daemon=True).start()

    def fetch_requests(self):
        found = []
        for index, repo in enumerate(REPOS if APPROVAL["label"] else []):
            got = subprocess.run(["gh", "issue", "list", "--repo", repo, "--label", APPROVAL["label"], "--state", "open",
                                  "--json", "number,title,body"], capture_output=True, text=True)
            try:
                issues = json.loads(got.stdout) if got.returncode == 0 else None
            except ValueError:
                issues = None
            if issues is None:
                # Not told this round: what was known of it stays.
                found += [request for request in self.requests if request["repo"] == repo]
                continue
            # The oldest first: the order they were asked in.
            found += [request for request in (asked(issue, repo, index) for issue in reversed(issues))
                      if request and (repo, request["number"]) not in self.over]
        self.requests = found

    def fetch(self):
        self.fetch_requests()
        runs, told = [], False
        for repo in REPOS:
            got = subprocess.run(["gh", "run", "list", "--repo", repo, "--limit", "20", "--json",
                                  "databaseId,workflowName,headBranch,headSha,status,conclusion,createdAt,startedAt,updatedAt"],
                                 capture_output=True, text=True)
            try:
                listed = json.loads(got.stdout) if got.returncode == 0 else None
            except ValueError:
                listed = None
            if listed is not None:
                told = True
                runs += [dict(run, repo=repo) for run in listed]
        if not told:
            return
        runs.sort(key=lambda run: run.get("createdAt", ""), reverse=True)
        self.runs = runs[:6]
        # Cancelling lasts until GitHub says the run is over.
        for run in runs:
            if run.get("status") == "completed" and self.working.get(run["databaseId"]) == "cancelling":
                del self.working[run["databaseId"]]
        typical = {}
        for run in runs:
            key = (run["repo"], run.get("workflowName"))
            if run.get("conclusion") == "success" and key not in typical:
                began, ended = moment(run.get("startedAt", ""), STAMP), moment(run.get("updatedAt", ""), STAMP)
                if began and ended and ended > began:
                    typical[key] = ended - began
        jobs = {}
        for run in runs:
            if run.get("status") != "in_progress":
                continue
            got = subprocess.run(["gh", "api", f"repos/{run['repo']}/actions/runs/{run['databaseId']}/jobs"],
                                 capture_output=True, text=True)
            try:
                listed = json.loads(got.stdout).get("jobs", []) if got.returncode == 0 else []
            except ValueError:
                listed = []
            for job in listed:
                if job.get("runner_name") and job.get("status") == "in_progress":
                    jobs[job["runner_name"]] = {"workflow": run["workflowName"], "steps": job.get("steps") or [],
                                                "started": moment(job.get("started_at") or "", STAMP),
                                                "typical": typical.get((run["repo"], run["workflowName"]))}
        self.jobs = jobs

    def carry_out(self, row, word, work):
        """`work` off the screen's thread, its row saying `word` until it is
        done; a cancel's until GitHub says so too."""
        self.working[row] = word
        def go():
            said, went = work()
            self.said = said
            if word != "cancelling" or not went:
                self.working.pop(row, None)
            self.fetch()
            # The list's own round may be asleep for 20 seconds. Two minutes
            # at most: a run gone from the list would otherwise say it for good.
            for _ in range(40):
                if row not in self.working:
                    return
                time.sleep(3)
                self.fetch()
            self.working.pop(row, None)
        threading.Thread(target=go, daemon=True).start()

    def loop(self):
        while True:
            self.fetch()
            time.sleep(20)


def run(*command):
    return subprocess.run(command, capture_output=True, text=True, timeout=10).stdout


def cpu():
    """All cores' busy share over the last second: top's second sample, its
    first being since the Mac started."""
    idle = re.findall(r"CPU usage:.*?([\d.]+)% idle", run("top", "-l", "2", "-n", "0", "-s", "1"))
    return 100 - float(idle[-1]) if idle else None


def gpu():
    found = re.search(r'"Device Utilization %"=(\d+)', run("ioreg", "-r", "-d", "1", "-w", "0", "-c", "IOAccelerator"))
    return int(found.group(1)) if found else None


def memory():
    """Used and all of it, in GB: active, wired and compressed pages, near
    what Activity Monitor calls Memory Used."""
    said = run("vm_stat")
    page = int(re.search(r"page size of (\d+) bytes", said).group(1))

    def pages(name):
        found = re.search(rf"{name}:\s+(\d+)", said)
        return int(found.group(1)) if found else 0

    used = (pages("Pages active") + pages("Pages wired down") + pages("Pages occupied by compressor")) * page
    return used / 2**30, int(run("sysctl", "-n", "hw.memsize")) / 2**30


def watts(load):
    """`SystemLoad` in watts. On battery it is negative, and ioreg prints it
    as the unsigned 64 bits: "18446744073709520 W", on battery."""
    if not load:
        return None
    return abs(load - (1 << 64) if load >= 1 << 63 else load) / 1000


def power():
    """The battery's own telemetry: what the whole Mac draws (`SystemLoad`,
    milliwatts, Apple silicon laptops), how full it is, whether it is on
    power and charging, and its temperature (hundredths of a degree). None
    without a battery."""
    said = run("ioreg", "-r", "-w", "0", "-c", "AppleSmartBattery")
    if not said.strip():
        return None

    def number(key):
        found = re.search(rf'"{key}"\s*=\s*(-?\d+)', said)
        return int(found.group(1)) if found else None

    def yes(key):
        return re.search(rf'"{key}"\s*=\s*Yes', said) is not None

    load, warm = number("SystemLoad"), number("Temperature")
    # A share on Apple silicon (of a MaxCapacity of 100), milliampere-hours
    # on an Intel Mac: the ratio is the percentage either way.
    full, most = number("CurrentCapacity"), number("MaxCapacity")
    return {"watts": watts(load), "external": yes("ExternalConnected"),
            "charging": yes("IsCharging"), "percent": 100 * full / most if full is not None and most else None,
            "warm": warm / 100 if warm else None}


def thermal():
    """How hot macOS says the Mac is, as it throttles by it: NSProcessInfo's
    thermalState, through the Objective-C runtime. A sensor's degrees would
    want sudo (powermetrics)."""
    objc = ctypes.cdll.LoadLibrary("/usr/lib/libobjc.A.dylib")
    ctypes.cdll.LoadLibrary("/System/Library/Frameworks/Foundation.framework/Foundation")
    objc.objc_getClass.restype = objc.sel_registerName.restype = ctypes.c_void_p
    objc.objc_getClass.argtypes = objc.sel_registerName.argtypes = [ctypes.c_char_p]
    send = objc.objc_msgSend
    send.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    send.restype = ctypes.c_void_p
    info = send(objc.objc_getClass(b"NSProcessInfo"), objc.sel_registerName(b"processInfo"))
    send.restype = ctypes.c_long
    state = send(info, objc.sel_registerName(b"thermalState"))
    return ("Nominal", "Fair", "Serious", "Critical")[state] if 0 <= state < 4 else None


class Machine:
    """What the Mac is doing, every few seconds, so a glance says whether
    it is too much."""

    READINGS = (("cpu", cpu), ("gpu", gpu), ("memory", memory), ("power", power), ("thermal", thermal))

    def __init__(self, once=False):
        self.now = {}
        # The last few minutes of CPU and GPU, for their graphs.
        self.cpu, self.gpu = deque(maxlen=200), deque(maxlen=200)
        if once:
            self.sample()
        else:
            threading.Thread(target=self.loop, daemon=True).start()

    def sample(self):
        now = {}
        for name, read in self.READINGS:
            # A reading this Mac does not give (no battery, another macOS)
            # is left out rather than taking the screen down with it.
            try:
                now[name] = read()
            except Exception:
                now[name] = None
        for history, value in ((self.cpu, now["cpu"]), (self.gpu, now["gpu"])):
            if value is not None:
                history.append(value)
        self.now = now

    def loop(self):
        # top's own second of sampling, then two more: a graph that moves.
        while True:
            self.sample()
            time.sleep(2)


# What the PC is asked, as one script on its stdin: the kernel's own counters
# (/proc, and the amdgpu and k10temp files in /sys), nothing to install and
# nothing to write. cpu is read twice, a second apart. `log` is last: all that
# follows it is the runner's journal.
PC_ASKS = r"""
echo "stat $(head -n1 /proc/stat)"
sleep 1
echo "stat $(head -n1 /proc/stat)"
echo "load $(cut -d' ' -f1 /proc/loadavg)"
echo "threads $(nproc)"
sed -n 's/^\(MemTotal\|MemAvailable\): *\([0-9]*\).*/mem_\1 \2/p' /proc/meminfo
for d in /sys/class/drm/card[0-9]/device; do
    [ -r "$d/gpu_busy_percent" ] || continue
    echo "gpu $(cat "$d/gpu_busy_percent")"
    echo "vram_used $(cat "$d/mem_info_vram_used" 2>/dev/null)"
    echo "vram_total $(cat "$d/mem_info_vram_total" 2>/dev/null)"
    for h in "$d"/hwmon/hwmon*; do
        echo "gpu_temp $(cat "$h/temp1_input" 2>/dev/null)"
        echo "gpu_power $(cat "$h/power1_average" "$h/power1_input" 2>/dev/null | head -n1)"
    done
    break
done
for h in /sys/class/hwmon/hwmon*; do
    [ "$(cat "$h/name" 2>/dev/null)" = k10temp ] && echo "cpu_temp $(cat "$h/temp1_input" 2>/dev/null)"
done
echo "runner $([ -n "$1" ] && systemctl --user is-active "$1" 2>/dev/null)"
echo log
[ -n "$1" ] && journalctl --user -u "$1" -n 200 --no-pager -o cat 2>/dev/null
exit 0
"""


def clean(text):
    """Only what can be printed: a line from another machine must not move the
    cursor or colour the screen on this one."""
    return "".join(character for character in text if character.isprintable())


def parse_pc(said):
    """A machine's answer as numbers and names. A key it did not give is left out,
    and so is a number that is not one."""
    head, _, log = said.partition("\nlog\n")
    got, stats = {}, []
    for line in head.splitlines():
        key, _, value = line.partition(" ")
        if key == "stat":
            stats.append(value.split()[1:])
        else:
            got[key] = value.strip()

    def number(key, scale=1.0):
        try:
            return float(got[key]) / scale
        except (KeyError, ValueError):
            return None

    now = {"threads": number("threads"), "load": number("load"), "gpu": number("gpu"),
           "cpu_temp": number("cpu_temp", 1000), "gpu_temp": number("gpu_temp", 1000),
           "gpu_power": number("gpu_power", 1e6), "runner": clean(got.get("runner", "")) or None}
    try:
        # user nice system idle iowait ...: busy is everything but idle and iowait.
        first, second = ([int(field) for field in stat] for stat in stats[:2])
        total = sum(second) - sum(first)
        idle = second[3] + second[4] - first[3] - first[4]
        now["cpu"] = 100 * (1 - idle / total) if total > 0 else None
    except (ValueError, IndexError):
        now["cpu"] = None
    total, free = number("mem_MemTotal", 2**20), number("mem_MemAvailable", 2**20)
    now["memory"] = (total - free, total) if total and free is not None else None
    used, size = number("vram_used", 2**30), number("vram_total", 2**30)
    now["vram"] = (used, size) if used is not None and size else None
    now["log"] = [clean(line) for line in log.splitlines()]
    return now


def ask_pc(host, service=""):
    """One round trip: the machine's answer, parsed, or None when it did not
    give one. Without a host it is this machine, asked with the same script."""
    # Checked again where it is used: a host that starts with a dash would be
    # an option to ssh.
    if (host is not None and not HOST.match(host)) or (service and not HOST.match(service)):
        return None
    command = ["sh", "-s", service]
    if host is not None:
        command = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", "-o", "ControlMaster=auto",
                   "-o", "ControlPersist=120", "-o", "ControlPath=" + os.path.expanduser("~/.ssh/runnerdeck-%C"),
                   "--", host, *command]
    got = subprocess.run(command, input=PC_ASKS, capture_output=True, text=True, timeout=20)
    return parse_pc(got.stdout) if got.returncode == 0 and got.stdout.strip() else None


class Pc:
    """A Linux machine, every few seconds: the same readings as the Mac's.
    Over ssh when it has a host, and here when it has none."""

    def __init__(self, name, host=None, service="", once=False):
        self.name, self.host, self.service = name, host, service
        self.now, self.at = {}, None
        self.cpu, self.gpu = deque(maxlen=200), deque(maxlen=200)
        if once:
            self.sample()
        else:
            threading.Thread(target=self.loop, daemon=True).start()

    def sample(self):
        try:
            now = ask_pc(self.host, self.service)
        except (OSError, subprocess.SubprocessError):
            now = None
        if now is None:
            # Kept as it was, but called stale: a machine that is off must
            # not look busy.
            self.at = None
            return
        for history, value in ((self.cpu, now["cpu"]), (self.gpu, now["gpu"])):
            if value is not None:
                history.append(value)
        self.now, self.at = now, time.time()

    def reachable(self):
        return self.at is not None

    def state(self):
        """The runner there, as a local one's: (state, job, since, last)."""
        if not self.reachable():
            return "unreachable", "", None, ""
        if self.now.get("runner") != "active":
            return "stopped", "", None, ""
        return said_by(self.now.get("log", []))

    def loop(self):
        while True:
            self.sample()
            time.sleep(2 if self.reachable() else 15)


def registration_token():
    repo = LOCAL["repo"]
    if shutil.which("gh"):
        got = subprocess.run(["gh", "api", "-X", "POST", f"repos/{repo}/actions/runners/registration-token",
                              "--jq", ".token"], capture_output=True, text=True)
        if got.returncode == 0 and got.stdout.strip():
            return got.stdout.strip()
    return input(f"A registration token (github.com/{repo} › Settings › Actions › Runners › "
                 "New self-hosted runner): ").strip()


def release():
    """The runner's download for this machine, GitHub's own names for them."""
    system = {"Darwin": "osx", "Linux": "linux"}.get(platform.system())
    arch = {"arm64": "arm64", "aarch64": "arm64", "x86_64": "x64", "AMD64": "x64"}.get(platform.machine())
    if not system or not arch:
        raise OSError(f"no runner for {platform.system()} {platform.machine()}")
    return f"https://github.com/actions/runner/releases/download/v{VERSION}/actions-runner-{system}-{arch}-{VERSION}.tar.gz"


def set_up(runner, token):
    print(f"Setting up {runner.name} in {runner.dir}")
    os.makedirs(runner.dir, exist_ok=True)
    url = release()
    curl = subprocess.Popen(["curl", "-fsSL", url], stdout=subprocess.PIPE)
    subprocess.run(["tar", "xz", "-C", runner.dir], stdin=curl.stdout, check=True)
    curl.stdout.close()
    if curl.wait():
        raise OSError(f"could not download {url}")
    subprocess.run(["./config.sh", "--url", f"https://github.com/{LOCAL['repo']}", "--token", token,
                    "--name", runner.name, "--unattended", "--replace"], cwd=runner.dir, check=True)


def start_all(runners):
    """Set up what is missing, unlock the keychain if there is one to unlock,
    start what is stopped."""
    missing = [runner for runner in runners if not runner.configured]
    if missing:
        token = registration_token()
        for runner in missing:
            try:
                set_up(runner, token)
            except (OSError, subprocess.CalledProcessError) as err:
                print(f"{runner.name} is not set up: {err}")
    stopped = [runner for runner in runners if runner.configured and not runner.running()]
    if stopped and KEYCHAIN and shutil.which("security") and os.path.exists(KEYCHAIN):
        print("The keychain, for signing:")
        if subprocess.run(["security", "unlock-keychain", KEYCHAIN]).returncode:
            print("Still locked: signing fails until it is unlocked.")
    for runner in stopped:
        runner.start()
    if not alive(AWAKE) and shutil.which("caffeinate"):
        awake = subprocess.Popen(["caffeinate", "-ims"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, start_new_session=True)
        write(AWAKE, awake.pid)
    keep_watch()


def keep_watch():
    """The watcher (--watch) beside the runners, apart from the screen as
    they are."""
    if not alive(WATCH):
        watcher = subprocess.Popen([sys.executable, os.path.abspath(__file__), "--watch"], stdin=subprocess.DEVNULL,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        write(WATCH, watcher.pid)


def stop_all(runners):
    for runner in runners:
        runner.stop()
    end(AWAKE)
    end(WATCH)


def notify(title, words, sound):
    def quoted(text):
        return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'

    if shutil.which("osascript"):
        command = ["osascript", "-e", f"display notification {quoted(words)} with title {quoted(title)} sound name {quoted(sound)}"]
    elif shutil.which("notify-send"):
        command = ["notify-send", "--", title, words]
    else:
        return
    subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def watch(runners):
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
                name = NAMES.get(job, job)
                good = result.lower() == "succeeded"
                notify(f"runnerdeck · {runner.name}", f"{name} {result.lower()}", "Glass" if good else "Basso")
                with open(JOBS, "a") as log:
                    log.write(f"{stamp}Z {runner.name} {name} {result}\n")


MARKS = {"running": "●", "listening": "○", "starting": "◌"}
WORDS = {"listening": "Listening", "starting": "Starting…", "stopped": "Stopped", "not set up": "Not set up"}
RESULTS = {"success": "✓", "failure": "✗", "cancelled": "–", "skipped": "–"}
BLOCKS = "▁▂▃▄▅▆▇█"
# The screen's colours by name, filled in by `colours` under curses; the
# text of --status has none, and draws an empty meter cell as a dot.
STYLE = {}


class Grid:
    """--status's screen: the same painting, as text."""

    def __init__(self, height, width):
        self.height, self.width = height, width
        self.rows = [[" "] * width for _ in range(height)]

    def put(self, y, x, text, style=""):
        if 0 <= y < self.height:
            for at, character in enumerate(text):
                if 0 <= x + at < self.width:
                    self.rows[y][x + at] = character

    def text(self):
        return "\n".join("".join(row).rstrip() for row in self.rows).rstrip()


class Screen:
    """The terminal, drawn here and not through curses, which now only hears
    the keys. The Mac's Python has the curses that counts bytes: "─" and "█"
    are three to it, so boxes lost their edges and bars came out as "�". One
    frame at a time, over the last, so nothing flickers."""

    def __init__(self, window):
        self.height, self.width = window.getmaxyx()
        self.rows = [[(" ", "")] * self.width for _ in range(self.height)]

    def put(self, y, x, text, style=""):
        if 0 <= y < self.height:
            for at, character in enumerate(text):
                if 0 <= x + at < self.width:
                    self.rows[y][x + at] = (character, style)

    def dim(self):
        """All of it pushed back, for what comes over it."""
        self.rows = [[(character, "under") for character, _ in row] for row in self.rows]

    def flush(self):
        out = ["\x1b[?7l"]
        for y, row in enumerate(self.rows, start=1):
            out.append(f"\x1b[{y};1H")
            now = None
            for character, style in row:
                if style != now:
                    out.append(f"\x1b[0;{STYLE.get(style, '')}m")
                    now = style
                out.append(character)
        out.append("\x1b[0m\x1b[?7h")
        sys.stdout.buffer.write("".join(out).encode("utf-8"))
        sys.stdout.buffer.flush()


def colours():
    """btop's way of looking: grey frames and labels, white for what matters,
    green to amber to red for how much; SGR's numbers, of 256 colours."""
    STYLE.update({
        "frame": "38;5;240",
        "label": "38;5;246",
        "plain": "38;5;252",
        "dim": "38;5;243",
        "strong": "1;38;5;255",
        "good": "38;5;114",
        "warm": "38;5;179",
        "bad": "1;38;5;167",
        "empty": "1;38;5;237",
        "picked": "7",
        # What a popup lies over, and the popup: a ground of its own.
        "under": "38;5;238",
        "pop": "38;5;252;48;5;236",
        "pop-strong": "1;38;5;255;48;5;236",
        "pop-frame": "38;5;250;48;5;236",
        "pop-off": "38;5;252;48;5;239",
        "pop-on": "1;38;5;234;48;5;255",
    })


def heat(share):
    return "good" if share < 0.6 else "warm" if share < 0.85 else "bad"


def frame(canvas, y, x, height, width, title, right=""):
    """A box with rounded corners, its title in the top edge, as btop's."""
    canvas.put(y, x, "╭─", "frame")
    canvas.put(y, x + 2, f" {title} ", "strong")
    start = x + 4 + len(title)
    end = x + width - 1 - (len(right) + 3 if right else 0)
    canvas.put(y, start, "─" * max(0, end - start), "frame")
    if right:
        canvas.put(y, end, f" {right} ", "label")
        canvas.put(y, x + width - 2, "─", "frame")
    canvas.put(y, x + width - 1, "╮", "frame")
    for row in range(y + 1, y + height - 1):
        canvas.put(row, x, "│", "frame")
        canvas.put(row, x + width - 1, "│", "frame")
    canvas.put(y + height - 1, x, "╰" + "─" * max(0, width - 2) + "╯", "frame")


def meter(canvas, y, x, width, share, style=None):
    """btop's meter: a row of blocks, each coloured by where it sits, so
    how full it is reads as how hot."""
    filled = round(max(0.0, min(1.0, share)) * width)
    for at in range(max(0, width)):
        if at < filled:
            canvas.put(y, x + at, "█", style or heat(at / max(width - 1, 1)))
        else:
            canvas.put(y, x + at, "█" if STYLE else "·", "empty")


def spark(canvas, y, x, width, history):
    """The history as a row of blocks, the newest at the right, each
    coloured by its height."""
    width = max(0, width)
    values = list(history)[-width:] if width else []
    canvas.put(y, x, "▁" * (width - len(values)), "empty")
    for at, value in enumerate(values):
        level = min(len(BLOCKS) - 1, int(value / 100 * len(BLOCKS)))
        canvas.put(y, x + width - len(values) + at, BLOCKS[level], heat(value / 100))


def right(canvas, y, width, text, style):
    canvas.put(y, width - 2 - len(text), text, style)


def mac_box(canvas, y, width, machine):
    """CPU and GPU as graphs, memory as a meter; beside them, or under them
    where the screen is narrow, what the battery says and how hot."""
    now = machine.now
    wide = width >= 96
    height = 5 if wide else 8
    frame(canvas, y, 0, height, width, "mac", f"load {os.getloadavg()[0]:.1f} · {os.cpu_count()} cores")
    half = (width - 4) // 2 - 1 if wide else width - 4
    row = y + 1
    for name, value, history in (("CPU", now.get("cpu"), machine.cpu), ("GPU", now.get("gpu"), machine.gpu)):
        canvas.put(row, 2, name, "label")
        spark(canvas, row, 7, half - 13, history)
        if value is None:
            canvas.put(row, half - 4, "  —", "dim")
        else:
            canvas.put(row, half - 4, f"{value:3.0f} %", heat(value / 100))
        row += 1
    used = now.get("memory")
    canvas.put(row, 2, "RAM", "label")
    if used:
        meter(canvas, row, 7, half - 22, used[0] / used[1])
        canvas.put(row, half - 13, f"{used[0]:4.1f} / {used[1]:.0f} GB", "plain")
    row = y + 1 if wide else row + 1
    x = half + 4 if wide else 2
    battery = now.get("power") or {}
    canvas.put(row, x, "Power", "label")
    if battery:
        watts = f"{battery['watts']:.0f} W  " if battery.get("watts") is not None else ""
        how = "charging" if battery["charging"] else "on power" if battery["external"] else "on battery"
        canvas.put(row, x + 9, watts, "strong")
        canvas.put(row, x + 9 + len(watts), how, "plain")
    else:
        canvas.put(row, x + 9, "—", "dim")
    row += 1
    canvas.put(row, x, "Battery", "label")
    percent, warm = battery.get("percent"), battery.get("warm")
    if percent is not None:
        # Low is under 20 % away from power.
        low = percent < 20 and not battery["external"]
        meter(canvas, row, x + 9, 12, percent / 100, "bad" if low else "warm" if percent < 40 else "good")
        canvas.put(row, x + 22, f"{percent:3.0f} %", "bad" if low else "plain")
    if warm is not None:
        canvas.put(row, x + 29, f"{warm:.0f} °C", "bad" if warm >= 45 else "plain")
    row += 1
    state = now.get("thermal")
    canvas.put(row, x, "Thermal", "label")
    # How hot, as macOS throttles by it: Serious or worse is too much.
    canvas.put(row, x + 9, state or "—", {"Nominal": "good", "Fair": "warm"}.get(state, "bad" if state else "dim"))
    return y + height


def hot(degrees, warm, bad):
    return "dim" if degrees is None else "bad" if degrees >= bad else "warm" if degrees >= warm else "plain"


def pc_box(canvas, y, width, pc):
    """A Linux machine as the Mac above it: CPU and GPU as graphs, memory as a meter;
    beside them, or under them, how hot it is, what the card draws, and its
    runner. A machine that does not answer says so, and shows no old numbers as
    if they were now."""
    now = pc.now if pc.reachable() else {}
    wide = width >= 96
    height = 5 if wide else 8
    host = pc.host.split("@")[-1] if pc.host else "here"
    if pc.reachable():
        right_side = f"{host} · load {now['load']:.1f} · {now['threads']:.0f} threads" if now.get("load") is not None else host
    else:
        right_side = f"{host} · not answering"
    frame(canvas, y, 0, height, width, pc.name, right_side)
    half = (width - 4) // 2 - 1 if wide else width - 4
    row = y + 1
    for name, value, history in (("CPU", now.get("cpu"), pc.cpu), ("GPU", now.get("gpu"), pc.gpu)):
        canvas.put(row, 2, name, "label")
        spark(canvas, row, 7, half - 13, history if pc.reachable() else [])
        if value is None:
            canvas.put(row, half - 4, "  —", "dim")
        else:
            canvas.put(row, half - 4, f"{value:3.0f} %", heat(value / 100))
        row += 1
    used = now.get("memory")
    canvas.put(row, 2, "RAM", "label")
    if used:
        meter(canvas, row, 7, half - 22, used[0] / used[1])
        canvas.put(row, half - 13, f"{used[0]:4.1f} / {used[1]:.0f} GB", "plain")
    row = y + 1 if wide else row + 1
    x = half + 4 if wide else 2
    canvas.put(row, x, "Heat", "label")
    # Ryzen's Tctl runs in the 80s under a build and holds to 95; the card's
    # edge sensor is cooler than its junction.
    cpu_temp, gpu_temp = now.get("cpu_temp"), now.get("gpu_temp")
    canvas.put(row, x + 9, f"CPU {cpu_temp:.0f} °C" if cpu_temp is not None else "CPU —", hot(cpu_temp, 80, 90))
    canvas.put(row, x + 21, f"GPU {gpu_temp:.0f} °C" if gpu_temp is not None else "GPU —", hot(gpu_temp, 75, 85))
    row += 1
    canvas.put(row, x, "Card", "label")
    power, vram = now.get("gpu_power"), now.get("vram")
    canvas.put(row, x + 9, f"{power:.0f} W" if power is not None else "—", "strong" if power is not None else "dim")
    if vram:
        canvas.put(row, x + 16, f"VRAM {vram[0]:.1f} / {vram[1]:.0f} GB", "plain")
    row += 1
    if not pc.service:
        return y + height
    state, job, since, last = pc.state()
    canvas.put(row, x, "Runner", "label")
    words = f"Running {job}" if state == "running" else {**WORDS, "unreachable": "Unreachable"}.get(state, state)
    canvas.put(row, x + 9, MARKS.get(state, "·"), "good" if state == "running" else "dim")
    canvas.put(row, x + 11, words[:max(0, width - x - 24)], "strong" if state == "running" else "dim" if state in ("stopped", "unreachable") else "plain")
    right(canvas, row, width, ago(since) if state in ("running", "listening") else "", "label")
    return y + height


def progress(job):
    """A busy runner's job: how far, which step, how long still. By the time
    the last good run of the workflow took where there was one — the steps
    are far from even, a Build is mostly app/build.sh — and by the steps
    where there was not."""
    steps = job["steps"]
    done = sum(1 for step in steps if step.get("status") == "completed")
    current = next((step.get("name", "") for step in steps if step.get("status") == "in_progress"), "")
    words = f"step {min(done + 1, len(steps))} of {len(steps)} · {current}" if steps else job["workflow"]
    elapsed = time.time() - job["started"] if job["started"] else None
    if job["typical"] and elapsed is not None:
        left = max(0, round((job["typical"] - elapsed) / 60))
        return min(elapsed / job["typical"], 0.99), words, f"~{left} min left" if left else "about done"
    return (done / len(steps) if steps else 0), words, ""


def runners_box(canvas, y, width, runners, queue):
    """Each runner: what it is doing in its own words, the last result in
    its colour, and a busy one's progress beside it, or under it where the
    screen is narrow."""
    wide = width >= 110
    rows = []
    for runner in runners:
        state, job, since, last = runner.state()
        busy = queue.jobs.get(runner.name) if state == "running" else None
        rows.append((runner, state, job, since, last, busy))
    height = 2 + len(rows) + sum(1 for row in rows if row[5] and not wide)
    busy_count = sum(1 for row in rows if row[1] == "running")
    frame(canvas, y, 0, height, width, "runners", f"{busy_count} of {len(rows)} busy")
    line = y + 1
    for runner, state, job, since, last, busy in rows:
        style = "strong" if state == "running" else "dim" if state in ("stopped", "not set up") else "plain"
        canvas.put(line, 2, MARKS.get(state, "·"), "good" if state == "running" else style)
        canvas.put(line, 4, runner.name, style)
        words = f"Running {job}" if state == "running" else WORDS[state]
        canvas.put(line, 11, words, style)
        if last and state != "running":
            canvas.put(line, 11 + len(words), " · last ", "dim")
            canvas.put(line, 19 + len(words), last, "bad" if "fail" in last else "good" if "succeed" in last else "plain")
        when = ago(since)
        if busy:
            share, steps, left = progress(busy)
            at, place = (line, 34) if wide else (line + 1, 11)
            meter(canvas, at, place, 16, share, "good")
            canvas.put(at, place + 18, steps[:max(0, width - place - 22 - len(left) - len(when) - 6)], "dim")
            if left:
                when = f"{left} · {when}" if wide else when
                if not wide:
                    right(canvas, at, width, left, "label")
        right(canvas, line, width, when, "label")
        line += 2 if busy and not wide else 1
    return y + height


def github_box(canvas, y, width, runs, picked=None, working=None):
    working = working or {}
    many = len({run.get("repo") for run in runs}) > 1
    frame(canvas, y, 0, 2 + len(runs), width, "github", ", ".join(REPOS) if len(", ".join(REPOS)) < width - 16 else f"{len(REPOS)} repositories")
    for line, run in enumerate(runs, start=y + 1):
        doing = working.get(run.get("databaseId"))
        if run.get("databaseId") == picked:
            canvas.put(line, 1, "▸" + " " * (width - 3), "picked")
            canvas.put(line, 4, run.get("workflowName", "")[:12], "picked")
            canvas.put(line, 17, run.get("headBranch", "")[:24], "picked")
            canvas.put(line, 42, run.get("headSha", "")[:7], "picked")
            if many:
                canvas.put(line, 50, run.get("repo", "").split("/")[-1][:16], "picked")
            word = f"{doing}…" if doing else run.get("conclusion") or (run.get("status") or "").replace("_", " ")
            right(canvas, line, width, f"{word} · {ago(moment(run.get('createdAt', ''), STAMP))}", "picked")
            continue
        done = run.get("status") == "completed"
        conclusion = run.get("conclusion") or ""
        mark = RESULTS.get(conclusion, "·") if done else "…" if run.get("status") == "in_progress" else "·"
        style = {"success": "good", "failure": "bad"}.get(conclusion, "dim") if done else "warm"
        canvas.put(line, 2, mark, style)
        canvas.put(line, 4, run.get("workflowName", "")[:12], "strong" if not done else "plain")
        canvas.put(line, 17, run.get("headBranch", "")[:24], "dim")
        canvas.put(line, 42, run.get("headSha", "")[:7], "dim")
        if many:
            canvas.put(line, 50, run.get("repo", "").split("/")[-1][:16], "dim")
        word = f"{doing}…" if doing else conclusion if done else (run.get("status") or "").replace("_", " ")
        when = ago(moment(run.get("createdAt", ""), STAMP))
        right(canvas, line, width, f"{word} · {when}", "warm" if doing else style if style != "dim" else "label")
    return y + 2 + len(runs)


def requests_box(canvas, y, width, requests, picked=None, working=None):
    working = working or {}
    frame(canvas, y, 0, 2 + len(requests), width, "waiting for you", "a: start · d: decline")
    for line, request in enumerate(requests, start=y + 1):
        chosen = row_of(request) == picked
        doing = working.get(row_of(request))
        if chosen:
            canvas.put(line, 1, "▸" + " " * (width - 3), "picked")
        else:
            canvas.put(line, 2, "?", "warm")
        canvas.put(line, 4, request["workflow"][:12], "picked" if chosen else "strong")
        canvas.put(line, 17, request["branch"][:24], "picked" if chosen else "dim")
        canvas.put(line, 42, request["sha"][:7], "picked" if chosen else "dim")
        words = f"{doing}…" if doing else request["note"]
        canvas.put(line, 50, words[:max(0, width - 52)], "picked" if chosen else "warm" if doing else "label")
    return y + 2 + len(requests)


def popup(canvas, dialog):
    """btop's way of asking: the screen pushed back, and a box of its own over
    it with its two answers; n, the safe one, is where it starts."""
    words = dialog["words"]
    width = min(max(len(words) + 8, 44), canvas.width - 2)
    height = 8
    x, y = (canvas.width - width) // 2, max(0, (canvas.height - height) // 2)
    canvas.dim()
    for row in range(y, y + height):
        canvas.put(row, x, " " * width, "pop")
    title = f" {dialog['title']} "
    canvas.put(y, x, "╭─", "pop-frame")
    canvas.put(y, x + 2, title, "pop-strong")
    canvas.put(y, x + 2 + len(title), "─" * max(0, width - 3 - len(title)) + "╮", "pop-frame")
    for row in range(y + 1, y + height - 1):
        canvas.put(row, x, "│", "pop-frame")
        canvas.put(row, x + width - 1, "│", "pop-frame")
    canvas.put(y + height - 1, x, "╰" + "─" * max(0, width - 2) + "╯", "pop-frame")
    canvas.put(y + 2, x + (width - len(words)) // 2, words[:width - 4], "pop-strong")
    # Which one Enter takes, in the words too and not only in the colour.
    yes = f" ▸ {dialog['yes']} " if dialog["focus"] else f"   {dialog['yes']} "
    no = f"   {dialog['no']} " if dialog["focus"] else f" ▸ {dialog['no']} "
    start = x + (width - len(yes) - len(no) - 2) // 2
    canvas.put(y + 5, start, yes, "pop-on" if dialog["focus"] else "pop-off")
    canvas.put(y + 5, start + len(yes) + 2, no, "pop-off" if dialog["focus"] else "pop-on")


def log_box(canvas, y, width, height, runner):
    """The log of the runner shown, its newest lines at the foot; a job's
    start in white, its end in the colour of how it ended."""
    frame(canvas, y, 0, height, width, f"log · {runner.name}", "tab: another")
    lines = [line for line in runner.tail() if line.strip()][-(height - 2):] if height > 2 else []
    for at, line in enumerate(lines, start=y + 1):
        style = ("bad" if "Failed" in line else "good" if "Succeeded" in line
                 else "strong" if "Running job" in line else "dim")
        canvas.put(at, 2, line[:width - 4], style)


def footer(canvas, y, width, note, picking=None):
    if note:
        canvas.put(y, 1, note[:width - 2], "warm")
        return
    x = 1
    keys = {"run": (("↑↓", "choose"), ("c", "cancel"), ("r", "run again"), ("o", "open"), ("esc", "back")),
            "request": (("↑↓", "choose"), ("enter", "start"), ("d", "decline"), ("esc", "back")),
            "dialog": (("y", "yes"), ("n", "no"), ("← →", "choose"), ("enter", "answer")),
            None: (("q", "leave, they keep running"), ("s", "start"), ("x", "stop"), ("tab", "another log"), ("↑↓", "choose"))}[picking]
    for key, words in keys:
        canvas.put(y, x, key, "strong")
        canvas.put(y, x + len(key) + 1, words, "label")
        x += len(key) + len(words) + 4


def paint(canvas, runners, queue, machine, shown, note, picked=None, dialog=None, pcs=()):
    """The whole screen: the head, this machine and the others, the runners,
    GitHub's last runs and a log, the log taking what is left and GitHub
    giving way first."""
    width, height = canvas.width, canvas.height
    canvas.put(0, 1, "◐ runnerdeck", "strong")
    awake = "awake" if alive(AWAKE) else "may sleep"
    told = " · notifying" if alive(WATCH) else ""
    if runners:
        right(canvas, 0, width + 1, f"{awake}{told}", "good" if alive(AWAKE) else "warm")
    y = 1
    if machine:
        y = mac_box(canvas, y, width, machine)
    for pc in pcs:
        y = pc_box(canvas, y, width, pc)
    if runners:
        y = runners_box(canvas, y, width, runners, queue)
    if queue.requests:
        y = requests_box(canvas, y, width, queue.requests, picked, queue.working)
    room = height - 1 - y
    if queue.runs and room >= 5:
        y = github_box(canvas, y, width, queue.runs[:max(1, min(len(queue.runs), room - 7))], picked, queue.working)
    if runners and height - 1 - y >= 3:
        log_box(canvas, y, width, height - 1 - y, runners[shown])
    picking = "dialog" if dialog else None if picked is None else "request" if picked < 0 else "run"
    if dialog:
        popup(canvas, dialog)
    # Last: its keys are read while a popup is up too.
    footer(canvas, height - 1, width, "" if dialog else note, picking)


ENTER = (10, 13, curses.KEY_ENTER)


def show(window, runners, queue, machine, pcs=()):
    try:
        curses.curs_set(0)
    except curses.error:
        pass
    colours()
    window.timeout(1000)
    # curses clears the screen once, at its first refresh: not over a frame.
    window.refresh()
    # By its row, not its place: the list moves as runs come in.
    shown, note, picked, dialog = 0, "", None, None

    def ask(title, words, yes, no, then):
        return {"title": title, "words": words, "yes": yes, "no": no, "then": then, "focus": False}

    def asks_for(item, letter):
        """The question before doing `letter` to a run or a request; None
        where it is not a thing to do, the foot then saying why."""
        nonlocal note
        row = row_of(item)
        if row in queue.working:
            note = f"Already {queue.working[row]}"
            return None
        if row < 0:
            what = f"{item['workflow']} from {item['branch']} at {item['sha'][:7]}"
            if letter == "a":
                def start():
                    said, closed = approve(item)
                    if closed:
                        queue.over.add((item["repo"], item["number"]))
                    return said, closed
                return ask(item["workflow"], f"Start {what}?", "Start", "Not now", lambda: queue.carry_out(row, "starting", start))
            def decline():
                close(item, "Declined in runnerdeck.")
                queue.over.add((item["repo"], item["number"]))
                return f"Declined {item['branch']} at {item['sha'][:7]}", True
            return ask(item["workflow"], f"Decline {what}?", "Decline", "Keep it", lambda: queue.carry_out(row, "declining", decline))
        what = f"{item.get('workflowName')} {item.get('headBranch')} {item.get('headSha', '')[:7]}"
        done = item.get("status") == "completed"
        if (letter == "c" and done) or (letter == "r" and not done):
            note = f"{item.get('workflowName')} is {'over' if done else 'still going'}"
            return None
        if letter == "c":
            return ask("Cancel", f"Cancel {what}?", "Cancel it", "Let it run", lambda: queue.carry_out(row, "cancelling", lambda: act_on_run(item, "c")))
        return ask("Run again", f"Run {what} again?", "Run it", "Leave it", lambda: queue.carry_out(row, "starting again", lambda: act_on_run(item, "r")))

    while True:
        if queue.said:
            note, queue.said = queue.said, ""
        screen = Screen(window)
        paint(screen, runners, queue, machine, shown, note, picked, dialog, pcs)
        screen.flush()
        key = window.getch()
        if key == -1:
            continue
        if key == curses.KEY_RESIZE:
            sys.stdout.buffer.write(b"\x1b[2J")
            continue
        if dialog:
            # Each arrow to its own side: both flipping it, → on the answer
            # already chosen chose the other, and a run was cancelled that
            # was meant to go on.
            if key == curses.KEY_LEFT:
                dialog["focus"] = True
            elif key == curses.KEY_RIGHT:
                dialog["focus"] = False
            elif key == 9:
                dialog["focus"] = not dialog["focus"]
            elif key == ord("y") or (key in ENTER and dialog["focus"]):
                dialog["then"]()
                dialog = None
            elif key in (ord("n"), ord("q"), 27) or key in ENTER:
                dialog = None
            continue
        if key == 27 and picked is not None:
            picked, note = None, ""
            continue
        if key in (ord("q"), 27):
            return
        requests, runs = queue.requests, queue.runs or []
        items = [*requests, *runs]
        if key in (curses.KEY_UP, curses.KEY_DOWN) and items:
            rows = [row_of(item) for item in items]
            step = 1 if key == curses.KEY_DOWN else -1
            at = rows.index(picked) + step if picked in rows else 0
            picked, note = rows[max(0, min(at, len(rows) - 1))], ""
            continue
        chosen = next((item for item in items if row_of(item) == picked), None)
        if key == ord("a") or (key in ENTER and chosen and row_of(chosen) < 0):
            request = chosen if chosen and row_of(chosen) < 0 else requests[0] if requests else None
            if request:
                dialog = asks_for(request, "a")
        elif key == ord("d"):
            request = chosen if chosen and row_of(chosen) < 0 else requests[0] if requests else None
            if request:
                dialog = asks_for(request, "d")
        elif chosen and row_of(chosen) > 0 and key in (ord("c"), ord("r")):
            dialog = asks_for(chosen, chr(key))
        elif chosen and row_of(chosen) > 0 and key == ord("o"):
            note = act_on_run(chosen, "o")[0]
        elif key == ord("x"):
            busy = [runner.name for runner in runners if runner.state()[0] == "running"]
            def stop():
                nonlocal note
                stop_all(runners)
                note = "Stopped; s starts them again"
            if busy:
                dialog = ask("Stop", f"Stop them? {', '.join(busy)} would fail its job", "Stop", "Keep running", stop)
            else:
                stop()
        elif key == 9 and runners:
            shown = (shown + 1) % len(runners)
        elif key == ord("s"):
            curses.endwin()
            start_all(runners)
            window.clear()
            window.refresh()
            note = ""


def read(path):
    try:
        with open(path) as file:
            return file.read()
    except OSError:
        return ""


def install():
    """This as ~/runnerdeck.py, and `runnerdeck` in the shell's rc to open it.
    Not in a login file: opening it at every login would start the runners
    with it."""
    target = os.path.expanduser("~/runnerdeck.py")
    if os.path.abspath(__file__) != target:
        shutil.copyfile(__file__, target)
    rc = os.path.expanduser("~/.zshrc" if os.path.basename(os.environ.get("SHELL", "")) == "zsh" else "~/.bashrc")
    if "runnerdeck.py" not in read(rc):
        with open(rc, "a") as file:
            file.write(f"\n# runnerdeck: starts the runners and shows them\nalias runnerdeck='{sys.executable} ~/runnerdeck.py'\n")
    print(f"{target}; `runnerdeck` opens it, in a new shell or after `source {rc}`.")


def init():
    if os.path.exists(CONFIG):
        print(f"{CONFIG} is there already; not touched.")
        return
    os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
    with open(CONFIG, "w") as file:
        file.write(EXAMPLE)
    print(f"{CONFIG} written: edit it, then run runnerdeck.py again.")


def machines(once=False):
    """This machine's box and the others'. A Mac is read with its own tools; a
    Linux machine, here or over ssh, with the one script (PC_ASKS)."""
    here = Machine(once) if platform.system() == "Darwin" else None
    pcs = [Pc(platform.node().split(".")[0][:12] or "here", None, "", once)] if here is None else []
    return here, pcs + [Pc(host["name"], host["ssh"], host["service"], once) for host in HOSTS]


def main(args):
    locale.setlocale(locale.LC_ALL, "")
    if "--help" in args or "-h" in args:
        print(__doc__)
        return
    if "--init" in args:
        init()
        return
    try:
        load()
    except (ConfigError, ValueError) as err:
        sys.exit(f"runnerdeck: {err}")
    runners = [Runner(n) for n in range(1, LOCAL["count"] + 1)] if LOCAL else []
    if "--install" in args:
        install()
        return
    if "--watch" in args:
        watch(runners)
        return
    if "--status" in args:
        here, pcs = machines(once=True)
        grid = Grid(34 + 5 * len(pcs), 100)
        paint(grid, runners, Queue(once=True), here, 0, "", pcs=pcs)
        print(grid.text())
        return
    if any(not runner.running() for runner in runners):
        start_all(runners)
    # Runners started before there was a watcher get one too.
    if any(runner.running() for runner in runners):
        keep_watch()
    here, pcs = machines()
    curses.wrapper(show, runners, Queue(), here, pcs)


if __name__ == "__main__":
    main(sys.argv[1:])
