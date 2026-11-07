"""CI health through `gh`: what is red, what is flaky, what is stale, the free disk, the issues that ask for a look.
Only when the config has a [health] section."""
import json
import os
import shutil
import subprocess
import threading
import time
from .util import STAMP, moment
from .terminal import frame, right

GREEN, RED = ("success",), ("failure", "timed_out", "startup_failure")
BUSY = ("in_progress", "queued", "waiting", "pending", "requested")
# Issue rows are numbers no run (a few 10^10) and no request (negative) has.
ISSUE_ROW = 10**12
GIB = 2**30


def howlong(seconds):
    """Short: 45 min, 3 h, 2 d."""
    minutes = max(0, int(seconds // 60))
    if minutes < 90:
        return f"{max(1, minutes)} min"
    if minutes < 48 * 60:
        return f"{round(minutes / 60)} h"
    return f"{round(minutes / 1440)} d"


def assess(runs, now):
    """The workflows of one repository, from its runs on the default branch: for each, what the last
    finished run said (`last`: green, red or None), whether one is going now, since when it has been red,
    and how many commits are flaky (a failed run and a later good run of the same commit). Red first."""
    by_name = {}
    for run in sorted(runs, key=lambda run: run.get("createdAt", ""), reverse=True):
        by_name.setdefault(run.get("workflowName", "?"), []).append(run)
    found = []
    for name, own in by_name.items():
        # `own` is the newest first; cancelled and skipped runs say nothing either way.
        done = [run for run in own if run.get("conclusion") in GREEN + RED]
        last = None if not done else "green" if done[0]["conclusion"] in GREEN else "red"
        since = None
        if last == "red":
            first = done[0]
            for run in done:
                if run["conclusion"] not in RED:
                    break
                first = run
            since = moment(first.get("createdAt", ""), STAMP)
        flaky = 0
        for sha in {run.get("headSha") for run in done}:
            same = [run for run in done if run.get("headSha") == sha]
            # `same` is the newest first: a good run with a failed one after it (older) is a recovery.
            if any(run["conclusion"] in GREEN and any(old["conclusion"] in RED for old in same[i + 1:]) for i, run in enumerate(same)):
                flaky += 1
        busy = any(run.get("status") in BUSY for run in own[:1])
        found.append({"name": name, "last": last, "busy": busy, "since": since, "flaky": flaky,
                      "red_for": now - since if since else None})
    found.sort(key=lambda item: (item["last"] != "red", not item["busy"], item["name"]))
    return found


def late(runs, now, minutes):
    """The queued runs that have waited longer than `minutes`: (workflow, minutes), longest first."""
    waited = []
    for run in runs:
        began = moment(run.get("createdAt", ""), STAMP)
        if began and now - began > minutes * 60:
            waited.append((run.get("workflowName", "?"), int((now - began) // 60)))
    return sorted(waited, key=lambda item: -item[1])


def disks(paths, minimum):
    """For each path: (path, free GiB or None where it cannot be read, whether that is under `minimum`)."""
    found = []
    for path in paths:
        try:
            free = shutil.disk_usage(os.path.expanduser(path)).free / GIB
        except OSError:
            free = None
        found.append((path, free, free is not None and free < minimum))
    return found


def open_issue(issue):
    """o on an issue: what to say of it, and whether it went."""
    got = subprocess.run(["gh", "issue", "view", str(issue["number"]), "--repo", issue["repo"], "--web"],
                         capture_output=True, text=True, timeout=15)
    if got.returncode:
        return f"#{issue['number']}: {got.stderr.strip() or 'gh said no'}", False
    return f"#{issue['number']} opened", True


def asked(command):
    """The JSON that `gh` printed, or None where it did not answer."""
    try:
        got = subprocess.run(["gh", *command], capture_output=True, text=True, timeout=30)
        return json.loads(got.stdout) if got.returncode == 0 else None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


class Health:
    """What `[health]` asks, read every two minutes (GitHub is asked about four times for each repository:
    more often than that is no use, a CI run takes minutes). `repos` has, for each repository, its
    workflows, the queued runs that wait too long and its open issues; one repository that does not
    answer keeps what was known of it."""

    EVERY = 120

    def __init__(self, cfg, once=False):
        self.cfg = cfg
        self.conf = cfg.health
        self.repos = {}
        self.issues = []
        self.smoke = {}
        self.disks = []
        self.default = {}
        self.loaded = False
        self.now = 0
        self.problem = ""
        if not shutil.which("gh"):
            self.problem = "gh is not installed: get it from https://cli.github.com"
            self.read_disks()
            return
        if once:
            self.fetch()
        else:
            threading.Thread(target=self.loop, daemon=True).start()

    def read_disks(self):
        paths = [self.cfg.local["dir"] if self.cfg.local else self.cfg.home] + self.conf["disk"]
        self.disks = disks(paths, self.conf["disk_min"])

    def fetch(self, now=None):
        now = now or time.time()
        conf, repos, why = self.conf, dict(self.repos), ""
        self.read_disks()
        for repo in conf["repos"]:
            if repo not in self.default:
                got = asked(["repo", "view", repo, "--json", "defaultBranchRef"])
                self.default[repo] = ((got or {}).get("defaultBranchRef") or {}).get("name", "") or None
            branch = self.default.get(repo)
            runs = asked(["run", "list", "--repo", repo, "--limit", "30", *(["--branch", branch] if branch else []),
                          "--json", "databaseId,workflowName,headSha,status,conclusion,createdAt"])
            if runs is None:
                why = why or f"{repo}: gh did not answer"
                self.default.pop(repo, None)
                continue
            queued = asked(["run", "list", "--repo", repo, "--status", "queued", "--limit", "30",
                            "--json", "databaseId,workflowName,createdAt"])
            issues = asked(["issue", "list", "--repo", repo, "--label", conf["label"], "--state", "open",
                            "--json", "number,title,url"])
            repos[repo] = {"flows": assess(runs, now), "late": late(queued or [], now, conf["queued_min"]),
                           "issues": issues if issues is not None else repos.get(repo, {}).get("issues", [])}
        smoke = dict(self.smoke)
        for repo, workflow in conf["smoke"]:
            green = asked(["run", "list", "--repo", repo, "--workflow", workflow, "--status", "success", "--limit", "1",
                           "--json", "createdAt"])
            if green is None:
                why = why or f"{repo}: no answer for {workflow}"
                continue
            # None where it was never green.
            smoke[(repo, workflow)] = moment(green[0]["createdAt"], STAMP) if green else None
        self.problem = why
        self.repos, self.smoke, self.loaded = repos, smoke, True
        self.issues = [dict(issue, repo=repo, row=ISSUE_ROW + index * 10**6 + issue["number"])
                       for index, repo in enumerate(conf["repos"]) for issue in repos.get(repo, {}).get("issues", [])]
        self.now = now

    def loop(self):
        while True:
            self.fetch()
            time.sleep(self.EVERY)

    def counts(self, now=None):
        """(red workflows, stale things, disks that are low): stale is a Smoke that is too old or never was
        green, and a run that waits too long."""
        now = now or time.time()
        red = sum(1 for repo in self.repos.values() for flow in repo["flows"] if flow["last"] == "red")
        old = sum(1 for when in self.smoke.values() if when is None or now - when > self.conf["smoke_days"] * 86400)
        waiting = sum(len(repo["late"]) for repo in self.repos.values())
        return red, old + waiting, sum(1 for _, _, low in self.disks if low)

    def words(self, now=None):
        """The one summary word of the head, as (text, style): all good, or what is red and stale."""
        if not self.loaded:
            return ("health: no answer", "warm") if self.problem else ("", "dim")
        red, stale, low = self.counts(now)
        parts = [f"{red} red"] * bool(red) + [f"{stale} stale"] * bool(stale) + ["low disk"] * bool(low)
        return (" · ".join(parts), "bad" if red else "warm") if parts else ("all good", "good")


def line_of(chips, canvas, y, x, width):
    """Chips, [(text, style), ...] one after another with two spaces between; what does not fit
    becomes "+N". Each chip is a list of (text, style) parts."""
    for number, chip in enumerate(chips):
        size = sum(len(text) for text, _ in chip)
        more = len(chips) - number - 1
        if x + size + (len(f"  +{more}") if more else 0) > width - 2:
            canvas.put(y, x, f"+{len(chips) - number}", "dim")
            return
        for text, style in chip:
            canvas.put(y, x, text, style)
            x += len(text)
        x += 2


def chips_for(flows):
    chips = []
    for flow in flows:
        red = flow["last"] == "red"
        mark, style = ("…", "warm") if flow["busy"] else ("✗", "bad") if red else ("✓", "good") if flow["last"] else ("·", "dim")
        chip = [(f"{mark} {flow['name']}", "bad" if red else style)]
        if red:
            chip.append((f"{' red' if flow['busy'] else ''} {howlong(flow['red_for'])}", "bad"))
        if flow["flaky"]:
            chip.append((f" flaky {flow['flaky']}", "warm"))
        chips.append(chip)
    return chips


def height_of(health):
    """The lines the box needs; 0 where there is nothing to show yet."""
    if not health or not health.loaded:
        return 0
    late_line = any(repo["late"] for repo in health.repos.values())
    return 3 + len(health.repos) + len(health.smoke) + late_line + min(len(health.issues), 4)


def health_box(canvas, y, width, health, picked=None, now=None):
    """The box: a line for each repository (red first, each workflow with how long it has been red and
    whether it is flaky), the free disk, the last good Smoke, what waits too long, and the open issues."""
    now = now or time.time()
    conf = health.conf
    frame(canvas, y, 0, height_of(health), width, "HEALTH", health.words(now)[0])
    labels = {repo: repo.split("/")[-1][:14] for repo in health.repos}
    at, line = 16, y + 1
    for repo, found in health.repos.items():
        canvas.put(line, 2, labels[repo], "plain")
        line_of(chips_for(found["flows"]) or [[("no runs", "dim")]], canvas, line, at, width)
        line += 1
    canvas.put(line, 2, "Disk", "label")
    chips = [[(f"{path.replace(health.cfg.home, '~', 1)} {free:.0f} GiB" if free is not None else f"{path.replace(health.cfg.home, '~', 1)} —", "bad" if low else "plain" if free is not None else "dim")]
             for path, free, low in health.disks]
    line_of(chips, canvas, line, at, width)
    line += 1
    for (repo, workflow), when in health.smoke.items():
        old = when is None or now - when > conf["smoke_days"] * 86400
        canvas.put(line, 2, "Smoke", "label")
        text = f"{workflow} · {repo.split('/')[-1]} · " + ("never green" if when is None else f"green {howlong(now - when)} ago")
        canvas.put(line, at, text + (" · stale" if old else ""), "warm" if old else "plain")
        line += 1
    waits = [(name, minutes, repo) for repo, found in health.repos.items() for name, minutes in found["late"]]
    if waits:
        canvas.put(line, 2, "Queued", "label")
        text = "   ".join(f"{name} {labels[repo]} {minutes} min" for name, minutes, repo in sorted(waits, key=lambda w: -w[1]))
        canvas.put(line, at, text[:max(0, width - at - 2)], "warm")
        line += 1
    for number, issue in enumerate(health.issues[:4]):
        chosen = issue["row"] == picked
        if chosen:
            canvas.put(line, 1, "▸" + " " * (width - 3), "picked")
        canvas.put(line, 2, conf["label"][:12] if number == 0 or chosen else "", "picked" if chosen else "label")
        canvas.put(line, at, f"#{issue['number']} {issue['title']}"[:max(0, width - at - 2)], "picked" if chosen else "bad")
        line += 1
    if len(health.issues) > 4:
        right(canvas, line - 1, width, f"+{len(health.issues) - 4} more", "dim")
    return y + height_of(health)
