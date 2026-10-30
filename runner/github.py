"""GitHub through `gh`: the last runs, the requests that wait for a person, what cancels or starts."""
import json
import shutil
import subprocess
import threading
import time
from .util import STAMP, moment


def asked(cfg, issue, repo="", index=0):
    """The request an issue makes, if its title is one: nothing from it but
    a workflow's name, a branch's name and a commit reaches `gh`. Its row is
    a negative number no run's can be, and none of another repository's."""
    found = cfg.asked.match(issue.get("title", "").strip()) if cfg.asked else None
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
    close(request, f"Approved in runner; {workflow} started.")
    return f"{workflow} started from {branch} at {sha[:7]}", True


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
        self.requests = []
        # A thing being done, by its row (`row_of`), and what the row says
        # meanwhile; requests over (repository, issue), which GitHub's list may
        # still show; and what the last one came to, for the foot.
        self.working = {}
        self.over = set()
        self.said = ""
        if not shutil.which("gh") or not self.cfg.repos:
            return
        if once:
            self.fetch()
        else:
            threading.Thread(target=self.loop, daemon=True).start()

    def fetch_requests(self):
        found = []
        for index, repo in enumerate(self.cfg.repos if self.cfg.approval["label"] else []):
            got = subprocess.run(["gh", "issue", "list", "--repo", repo, "--label", self.cfg.approval["label"], "--state", "open",
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
            found += [request for request in (asked(self.cfg, issue, repo, index) for issue in reversed(issues))
                      if request and (repo, request["number"]) not in self.over]
        self.requests = found

    def fetch(self):
        self.fetch_requests()
        runs, told = [], False
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
