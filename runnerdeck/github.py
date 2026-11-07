"""GitHub through `gh`: the last runs, the requests that wait for a person, what cancels or starts."""
import json
import shutil
import subprocess
import threading
import time
from .util import STAMP, clean, moment


def asked(cfg, issue, repo="", index=0, label=None):
    """The request an issue makes, if its title is one: nothing from it but
    a workflow's name, a branch's name and a commit reaches `gh`. Its row is
    a negative number no run's can be, and none of another repository's.
    With a `label`, only the kinds of that label are tried."""
    title = issue.get("title", "").strip()
    row = -(index * 10**6 + issue["number"])
    note = (issue.get("body") or "").split("\n")[0]
    found = cfg.asked.match(title) if cfg.asked and label in (None, cfg.approval["label"]) else None
    if found:
        return {"number": issue["number"], "repo": repo, "row": row, "workflow": found[1], "branch": found[2],
                "sha": found[3], "note": note, "kind": "", "ref": found[2], "inputs": {}, "target": repo,
                "what": f"{found[1]} from {found[2]} at {found[3][:7]}"}
    for kind in getattr(cfg, "kinds", ()):
        found = kind["title"].match(title) if label in (None, kind["label"]) else None
        if not found:
            continue
        values = found.groupdict()
        ref = values["branch"] if kind["ref"] == "{branch}" else kind["ref"]
        # The inputs that the workflow gets: each a field of the title, which has been checked, or a plain word.
        inputs = {key: values.get(value[1:-1], value) if value.startswith("{") else value for key, value in kind["inputs"].items()}
        return {"number": issue["number"], "repo": repo, "row": row, "workflow": kind["workflow"], "branch": ref or "",
                "sha": values.get("sha", ""), "note": note, "kind": kind["name"], "ref": ref, "inputs": inputs, "target": kind["repo"] or repo,
                "what": title[:60]}
    return None


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


def failed_log(run, limit=60):
    """The end of what a run's failed steps wrote, as GitHub keeps it: the lines, or why there are none."""
    got = subprocess.run(["gh", "run", "view", str(run["databaseId"]), "--repo", run["repo"], "--log-failed"],
                         capture_output=True, text=True, timeout=45)
    if got.returncode:
        return [got.stderr.strip().splitlines()[-1] if got.stderr.strip() else "gh could not read the log"]
    lines = []
    for line in got.stdout.splitlines():
        # "job<TAB>step<TAB>2026-10-31T16:42:50.123Z message": the message is what was said.
        parts = line.split("\t", 2)
        lines.append(clean(parts[2].split(" ", 1)[1] if len(parts) == 3 and " " in parts[2] else line))
    return lines[-limit:] or ["Nothing failed in this run, or GitHub keeps no log of it."]


def row_of(item):
    """A row of the screen by what it is, as it moves: a run's number, a
    request's as a negative one."""
    return item["row"] if "row" in item else item["databaseId"]


def approve(request):
    """Starts the workflow asked for; what to say of it, and whether the
    request is over."""
    repo, workflow, branch, sha = request["target"], request["workflow"], request["ref"], request["sha"]
    if branch and sha and not still_at(repo, branch, sha):
        return f"{branch} is no longer at {sha[:7]}: nothing started", False
    # One each: a run started by hand, or the list of requests lagging behind
    # a close, and a key pressed again queued the same commit again.
    runs = subprocess.run(["gh", "run", "list", "--repo", repo, "--workflow", workflow, *(["--branch", branch] if branch else []),
                           "--limit", "10", "--json", "status,headSha"], capture_output=True, text=True, timeout=15)
    try:
        listed = json.loads(runs.stdout) if runs.returncode == 0 else None
    except ValueError:
        listed = None
    if listed is None:
        return "GitHub did not say what is running: nothing started", False
    if sha and any(run["headSha"].startswith(sha) and run["status"] != "completed" for run in listed):
        close(request, f"A {workflow} of this commit is already on its way.")
        return f"{sha[:7]} is already on its way: nothing started", True
    # The command is made of what the config names and of values that were checked against a pattern.
    command = ["gh", "workflow", "run", workflow, "--repo", repo]
    if branch:
        command += ["--ref", branch]
    for key, value in request["inputs"].items():
        command += ["-f", f"{key}={value}"]
    started = subprocess.run(command, capture_output=True, text=True, timeout=15)
    if started.returncode:
        return f"{workflow} did not start: {started.stderr.strip()}", False
    close(request, f"Approved in runner; {workflow} started.")
    return f"{request['what']}: {workflow} started", True


def close(request, words):
    subprocess.run(["gh", "issue", "close", str(request["number"]), "--repo", request["repo"], "--comment", words],
                   capture_output=True, text=True, timeout=15)


class Queue:
    """GitHub's last runs of every repository, every 20 seconds, while `gh` can
    say; and for each runner busy with one, how far its job is — the steps
    GitHub counts, and the time the last good run of that workflow took."""

    def __init__(self, cfg, once=False):
        self.cfg = cfg
        self.runs = None
        self.jobs = {}
        # Which runner has a run, or what it waits for, by the run's number.
        self.on = {}
        self.requests = []
        # Whether runnerdeck itself has a newer version (see update.behind); set by the screen.
        self.update_ready = False
        # A thing being done, by its row (`row_of`), and what the row says
        # meanwhile; requests over (repository, issue), which GitHub's list may
        # still show; and what the last one came to, for the foot.
        self.working = {}
        self.over = set()
        self.said = ""
        # Why there are no runs, when there are none: shown instead of a silent gap.
        self.problem = ""
        self.at = None
        if not shutil.which("gh") or not self.cfg.repos:
            self.problem = "gh is not installed: get it from https://cli.github.com"
            return
        if once:
            self.fetch()
        else:
            threading.Thread(target=self.loop, daemon=True).start()

    def fetch_requests(self):
        found = []
        labels = list(dict.fromkeys(([self.cfg.approval["label"]] if self.cfg.approval["label"] else [])
                                    + [kind["label"] for kind in self.cfg.kinds]))
        for index, repo in enumerate(self.cfg.repos):
            seen, told = set(), True
            for label in labels:
                got = subprocess.run(["gh", "issue", "list", "--repo", repo, "--label", label, "--state", "open",
                                      "--json", "number,title,body"], capture_output=True, text=True)
                try:
                    issues = json.loads(got.stdout) if got.returncode == 0 else None
                except ValueError:
                    issues = None
                if issues is None:
                    told = False
                    continue
                # The oldest first: the order they were asked in.
                for issue in reversed(issues):
                    request = asked(self.cfg, issue, repo, index, label)
                    if request and issue["number"] not in seen and (repo, issue["number"]) not in self.over:
                        seen.add(issue["number"])
                        found.append(request)
            if not told:
                # Not told this round: what was known of it stays.
                found += [request for request in self.requests if request["repo"] == repo and request["number"] not in seen]
        self.requests = found

    def fetch(self):
        self.fetch_requests()
        runs, told, why = [], False, ""
        for repo in self.cfg.repos:
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
            elif not why:
                lines = [line.strip() for line in (got.stderr or "").splitlines() if line.strip()]
                why = f"{repo}: {lines[0]}" if lines else f"{repo}: gh did not answer"
        self.problem = "" if told else why
        if not told:
            return
        # When GitHub last answered: the screen says how old the list is.
        self.at = time.time()
        runs.sort(key=lambda run: run.get("createdAt", ""), reverse=True)
        # Enough for the RUNS page; the deck shows as many as fit.
        self.runs = runs[:20]
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
        jobs, on = {}, {}
        for run in runs:
            if run.get("status") not in ("in_progress", "queued"):
                continue
            got = subprocess.run(["gh", "api", f"repos/{run['repo']}/actions/runs/{run['databaseId']}/jobs"],
                                 capture_output=True, text=True)
            try:
                listed = json.loads(got.stdout).get("jobs", []) if got.returncode == 0 else []
            except ValueError:
                listed = []
            # Where it is: the runners that have its jobs, or what its jobs wait for.
            names = sorted({job["runner_name"] for job in listed if job.get("runner_name") and job.get("status") == "in_progress"})
            waits = sorted({label for job in listed if job.get("status") == "queued" for label in job.get("labels", [])
                            if label != "self-hosted"})
            if names:
                on[run["databaseId"]] = ", ".join(names)
            elif waits:
                on[run["databaseId"]] = "waiting for " + "/".join(waits)
            for job in listed:
                if job.get("runner_name") and job.get("status") == "in_progress":
                    jobs[job["runner_name"]] = {"workflow": run["workflowName"], "steps": job.get("steps") or [],
                                                "started": moment(job.get("started_at") or "", STAMP),
                                                "typical": typical.get((run["repo"], run["workflowName"]))}
        self.jobs, self.on = jobs, on

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


DETAIL = {}


def run_detail(run):
    """The jobs and steps of a run (and its title and event), asked of gh in the background: None while it is
    asked, {} where gh could not say. Asked again when the run's status changes, and every ten seconds while
    it goes on, so that its steps move."""
    key = (run["databaseId"], run.get("status"))
    entry = DETAIL.get(key)
    again = entry and run.get("status") != "completed" and not entry["asking"] and time.time() - entry["at"] > 10
    if entry is None or again:
        entry = DETAIL.setdefault(key, {"value": None})
        entry.update(at=time.time(), asking=True)

        def ask():
            try:
                got = subprocess.run(["gh", "run", "view", str(run["databaseId"]), "--repo", run.get("repo", ""),
                                      "--json", "jobs,event,displayTitle"], capture_output=True, text=True, timeout=20)
                entry["value"] = json.loads(got.stdout) if got.returncode == 0 else (entry["value"] or {})
            except (OSError, ValueError, subprocess.TimeoutExpired):
                entry["value"] = entry["value"] or {}
            entry["asking"] = False
        threading.Thread(target=ask, daemon=True).start()
    return entry["value"]
