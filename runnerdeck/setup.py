"""First start: the questions that make the config file, one at a time, on the terminal screen."""
import configparser
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import textwrap
import threading
import time
from .config import ConfigError, HOST, REFERENCE, SLUG, WORD, configure, default_path, set_approval
from .runners import Runner, TOKEN, find_runners, gh_token, plan_of, set_up
from .terminal import K_BACKSPACE, K_DOWN, K_RESIZE, K_UP, Screen, colours, frame

# Each step: its kind (info, text or yesno) and the title on the right of its frame.
STEPS = {
    "welcome": ("info", "Welcome"),
    "repos": ("text", "Repositories"),
    "count": ("text", "Runners on this machine"),
    "name": ("text", "Name of the runners"),
    "dir": ("text", "Folder of the runners"),
    "local_repo": ("text", "Repository of the runners"),
    "token": ("text", "Registration token"),
    "other": ("yesno", "Another machine"),
    "ssh": ("text", "SSH address"),
    "service": ("text", "Runner service"),
    "approval": ("yesno", "Approval"),
    "workflows": ("text", "Workflows"),
    "label": ("text", "Label"),
    "command": ("yesno", "The runnerdeck command"),
    "review": ("info", "Check the config"),
    "save": ("info", "Saved"),
    "work": ("info", "Setting up the runners"),
    "done": ("info", "Done"),
}


class Checks:
    """What the questions ask of the machine. Tests put their own in place."""

    def gh(self):
        """(installed, signed in)"""
        if not shutil.which("gh"):
            return False, False
        try:
            return True, subprocess.run(["gh", "auth", "status"], capture_output=True, timeout=15).returncode == 0
        except (OSError, subprocess.SubprocessError):
            return True, False

    def repo(self, repo):
        """True if gh can see it, False if not, None if gh cannot say."""
        if not shutil.which("gh"):
            return None
        try:
            got = subprocess.run(["gh", "api", f"repos/{repo}", "--jq", ".full_name"], capture_output=True, text=True, timeout=20)
        except (OSError, subprocess.SubprocessError):
            return None
        return got.returncode == 0

    def workflows(self, repo):
        """The names of the workflows of a repository, as GitHub lists them; none if gh cannot say."""
        if not shutil.which("gh"):
            return []
        try:
            got = subprocess.run(["gh", "workflow", "list", "--repo", repo, "--json", "name", "--limit", "100"],
                                 capture_output=True, text=True, timeout=20)
            return [item["name"] for item in json.loads(got.stdout)] if got.returncode == 0 else []
        except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
            return []

    def labels(self, repo):
        """The names of the labels of a repository; none if gh cannot say."""
        if not shutil.which("gh"):
            return []
        try:
            got = subprocess.run(["gh", "label", "list", "--repo", repo, "--json", "name", "--limit", "100"],
                                 capture_output=True, text=True, timeout=20)
            return [item["name"] for item in json.loads(got.stdout)] if got.returncode == 0 else []
        except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
            return []

    def ssh(self, host):
        """(connected, and if not, why in words a person can use)"""
        try:
            got = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", "--", host, "true"],
                                 capture_output=True, text=True, timeout=20)
        except (OSError, subprocess.SubprocessError):
            return False, explain_ssh("timed out", host)
        return (True, "") if got.returncode == 0 else (False, explain_ssh(got.stderr, host))


def explain_ssh(stderr, host):
    """What ssh said, as a thing a person can do something about."""
    said = (stderr or "").lower()
    if "host key verification failed" in said or "no matching host key" in said:
        return f"This computer does not know the PC yet. Run this once, answer yes, and try again: ssh {host}"
    if "connection refused" in said:
        return "The PC refuses the connection. Its SSH server is probably off. On Linux: sudo systemctl enable --now sshd"
    if "permission denied" in said:
        return f"The PC answers, but does not accept your key. Add it once: ssh-copy-id {host}"
    if "could not resolve" in said or "name or service not known" in said:
        return "That name is not known. Try the IP address."
    if "timed out" in said or "no route to host" in said or "unreachable" in said:
        return "No answer. Check the address, and that the PC is on and on the same network."
    lines = [line.strip() for line in (stderr or "").splitlines() if line.strip()]
    return lines[-1] if lines else "It did not connect."


def make_runner(cfg, n, token):
    """Starts runner number n, after setting it up if it is not set up yet. A
    runner that is there already is never downloaded or registered again.
    Raises what went wrong."""
    runner = Runner(cfg, n)
    if not runner.configured:
        set_up(cfg, runner, token, quiet=True)
    if not runner.running():
        runner.start()
    return runner


def config_text(answers):
    """The config file for these answers. Only checked values are in it."""
    text = "[deck]\nrepos = " + ", ".join(answers["repos"]) + "\n"
    if answers["count"]:
        text += f"\n[local]\nname = {answers['name']}\ndir = {answers['dir']}\ncount = {answers['count']}\n"
        if len(answers["repos"]) > 1:
            text += f"repo = {answers['local_repo']}\n"
    if answers["other"]:
        text += f"\n[host {answers['host_name']}]\nssh = {answers['ssh']}\n"
        if answers["service"]:
            text += f"service = {answers['service']}\n"
    if answers["approval"]:
        text += f"\n[approval]\nworkflows = {', '.join(answers['workflows'])}\nlabel = {answers['label']}\n"
    return text + "\n" + REFERENCE


class Wizard:
    """The questions as a machine that is fed keys and shows a view: the screen
    only draws it, so it can be tested without a terminal."""

    SLOW = {"repos": "Asking GitHub…", "ssh": "Trying to connect…"}
    SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def __init__(self, checks=None, install=None, make=None, path=None, finder=None, start="welcome", seed=None,
                 typed=None, mode="setup", threaded=True):
        self.mode, self.saved = mode, False
        # What is waited for: its words, whether the question is hidden meanwhile, which wait it is
        # (an answer of an older one is dropped), and the answer when it has come.
        self.busy, self.hide, self.generation, self.arrived, self.threaded = None, False, 0, None, threaded
        self.checks = checks or Checks()
        self.finder = finder or find_runners
        self.install = install
        self.make = make or make_runner
        self.path = path or default_path()
        name = re.sub(r"[^A-Za-z0-9_-]", "", platform.node().split(".")[0].lower()) or "box"
        self.answers = {"repos": [], "count": 0, "name": name, "dir": "~/actions-runner", "local_repo": "", "token": "",
                        "other": False, "ssh": "", "host_name": "pc", "service": "", "approval": False,
                        "workflows": [], "label": "", "command": True}
        self.answers.update(seed or {})
        self.step, self.history, self.typed = start, [], dict(typed or {})
        self.field, self.note, self.bad, self.kept, self.fresh = "", "", False, False, False
        self.cfg = self.installed = self.problem = None
        self.finished = self.cancelled = self.working = False
        self.progress = []
        self.gh = (False, False)
        self.found, self.plan, self.left = [], None, []
        # The workflows to choose from, which of them, and how many names the program cannot use.
        self.options, self.cursor, self.picked, self.skipped, self.labels = [], 0, set(), 0, []
        self.enter()

    @classmethod
    def for_approval(cls, cfg, checks=None, path=None, threaded=True):
        """Only the workflows that wait for a yes, chosen again from the list, for a
        config that is there already. What is set now is chosen to begin with."""
        typed = {"label": cfg.approval["label"]} if cfg.approval["label"] else None
        return cls(checks, path=path, start="workflows", mode="approval", typed=typed, threaded=threaded,
                   seed={"repos": cfg.repos, "workflows": list(cfg.approval["workflows"])})

    # ---- moving between steps
    def enter(self):
        self.field = self.typed.get(self.step) or self.default(self.step)
        # What is offered is replaced by the first key typed; backspace edits it.
        self.fresh = bool(self.field)
        self.note, self.bad, self.kept, self.kept_parsed = "", False, False, None
        if self.step == "welcome":
            def looked(result):
                self.gh, self.found = result
                # Runners that are there already are offered, not made again.
                self.plan, self.left = plan_of(self.found)
                if self.plan:
                    self.answers["name"], self.answers["dir"] = self.plan["name"], self.plan["dir"]
                self.field = self.default("welcome")
            self.later("Looking at this computer…", lambda: (self.checks.gh(), self.finder()), looked, hide=True)
        elif self.step == "workflows":
            def listed(result):
                self.options, self.skipped, self.labels = result
                self.cursor = 0
                chosen = self.answers["workflows"]
                self.picked = {i for i, name in enumerate(self.options) if name in chosen}
            self.later("Asking GitHub for the workflows and labels…", self.lookup, listed, hide=True)
        elif self.step == "save":
            self.save()
        elif self.step == "work":
            self.working = True
            threading.Thread(target=self.work, daemon=True).start()

    def save(self):
        a = self.answers
        try:
            set_approval(self.path, a["workflows"], a["label"])
            self.saved = True
        except (ConfigError, OSError) as err:
            self.note, self.bad = f"Not saved: {err}", True

    def later(self, words, work, then, hide=False):
        """work() off the screen's thread, with its words and a spinner on the screen meanwhile;
        then(its answer) back on the screen's thread, from tick."""
        if not self.threaded:
            then(work())
            return
        self.generation += 1
        mine = self.generation
        self.busy, self.hide, self.note = words, hide, ""

        def run():
            try:
                result = work()
            except Exception as err:
                result = err
            self.arrived = (mine, then, result)
        threading.Thread(target=run, daemon=True).start()

    def tick(self):
        """Takes the answer of what was waited for, if it has come. Called by the screen's loop."""
        got, self.arrived = self.arrived, None
        if got and got[0] == self.generation and self.busy:
            self.busy, self.hide = None, False
            if isinstance(got[2], Exception):
                self.note, self.bad = f"Something went wrong: {got[2]}", True
            else:
                got[1](got[2])

    def remember(self):
        """What was typed stays when the step is left and come back to. What was only
        offered does not: it is offered again, from what is known by then."""
        if self.fresh:
            self.typed.pop(self.step, None)
        else:
            self.typed[self.step] = self.field

    def lookup(self):
        """The workflows of the repositories, those whose names the program can use, how many it
        cannot, and the labels that the repositories have."""
        names, labels = [], []
        for repo in self.answers["repos"]:
            names += [name for name in self.checks.workflows(repo) if name not in names]
            labels += [name for name in self.checks.labels(repo) if name not in labels]
        usable = [name for name in names if WORD.match(name)]
        return usable, len(names) - len(usable), labels

    def default_label(self):
        """The label to offer: one that is on GitHub already and fits a chosen workflow (a label
        with its name in it, like testflight-request for TestFlight), else workflow-request."""
        chosen = self.answers["workflows"]
        if not chosen:
            return ""
        derived = chosen[0].lower().replace(" ", "-") + "-request"
        if derived in self.labels:
            return derived
        for workflow in chosen:
            words = workflow.lower().split()
            for label in self.labels:
                parts = re.split(r"[^a-z0-9]+", label.lower())
                if "request" in parts and all(word in parts for word in words):
                    return label
        return derived

    def kind(self):
        """Choosing from a list, if gh gave one; else typing the names."""
        return "pick" if self.step == "workflows" and self.options else STEPS[self.step][0]

    def go(self, step):
        self.history.append(self.step)
        self.step = step
        self.enter()

    def back(self):
        if self.working or self.step in ("work", "done"):
            return
        if not self.history:
            self.finished = self.cancelled = True
            return
        self.remember()
        self.step = self.history.pop()
        self.enter()

    # ---- keys
    def feed(self, key):
        if self.finished or key == K_RESIZE:
            return
        if self.busy:
            # Only escape: stop waiting. A question that was hidden meanwhile goes back a step.
            if key == 27:
                self.generation += 1
                hidden, self.busy, self.hide = self.hide, None, False
                if hidden:
                    self.back()
            return
        kind = self.kind()
        if key == 27:
            return self.back()
        if kind == "pick":
            if key == K_UP:
                self.cursor = max(0, self.cursor - 1)
            elif key == K_DOWN:
                self.cursor = min(len(self.options) - 1, self.cursor + 1)
            elif key == 32:
                self.picked ^= {self.cursor}
            elif key in (10, 13, 343):
                if not self.picked and self.mode != "approval":
                    self.note, self.bad = "Choose at least one with the space bar. Or press Esc and answer n.", True
                else:
                    self.answers["workflows"] = [self.options[i] for i in sorted(self.picked)]
                    self.go(self.after())
        elif kind == "info":
            if key in (10, 13, 343) and not self.working:
                self.advance()
        elif kind == "yesno":
            letter = chr(key).lower() if 32 <= key < 127 else ""
            if letter in ("y", "n") or key in (10, 13, 343):
                self.answers[self.step] = (letter == "y") if letter else self.default(self.step) == "y"
                self.go(self.after())
        else:
            if key in (10, 13, 343):
                self.submit()
            elif key in (8, 127, K_BACKSPACE):
                self.field, self.kept, self.fresh = self.field[:-1], False, False
            elif 32 <= key < 127:
                self.field, self.kept = ("" if self.fresh else self.field) + chr(key), False
                self.fresh = False

    def submit(self):
        step, value = self.step, self.field.strip()
        if self.kept:
            # A warning was said about this answer and it is the same: keep it, do not check again.
            self.remember()
            self.answers[step] = self.kept_parsed
            return self.go(self.after())
        words = self.SLOW.get(step)
        if words:
            self.later(words, lambda: self.check(step, value), self.judged)
        else:
            self.judged(self.check(step, value))

    def judged(self, result):
        error, warning, parsed = result
        if error:
            self.note, self.bad = error, True
            return
        if warning and not self.kept:
            self.note, self.bad, self.kept, self.kept_parsed = warning, False, True, parsed
            return
        self.remember()
        self.answers[self.step] = parsed
        self.go(self.after())

    def advance(self):
        if self.step == "welcome":
            return self.go("repos")
        if self.step == "review":
            return self.write()
        if self.step == "work":
            return self.go("done")
        self.finished = True

    # ---- the questions
    def default(self, step):
        a = self.answers
        # The repository of the row that can be managed first: new runners go there.
        first = [self.plan["repo"]] if self.plan and self.plan["repo"] else []
        repos = list(dict.fromkeys(first + [item["repo"] for item in self.found if item["repo"]]))
        return {"repos": ", ".join(repos), "count": str(self.plan["count"]) if self.plan else "0", "name": a["name"], "dir": a["dir"], "local_repo": self.plan["repo"] if self.plan and self.plan["repo"] in a["repos"] else (a["repos"] or [""])[0],
                "token": "", "other": "n", "ssh": "", "service": "", "approval": "n", "workflows": ", ".join(a["workflows"]),
                "label": self.default_label(),
                "command": "y"}.get(step, "")

    def missing_runners(self):
        """The numbers of the runners that are not set up yet: no .runner file in their folder."""
        a = self.answers
        base = os.path.expanduser(a["dir"])
        return [n for n in range(1, a["count"] + 1)
                if not os.path.exists(os.path.join(base if n == 1 else f"{base}-{n}", ".runner"))]

    def after(self):
        a, step = self.answers, self.step
        # A token is for registering a runner: asked only when one is missing.
        registering = "token" if self.missing_runners() else "other"
        return {"repos": "count", "name": "dir", "local_repo": registering, "token": "other", "ssh": "service",
                "service": "approval", "command": "review",
                "workflows": "label" if self.mode == "setup" or a["workflows"] else "save",
                "label": "command" if self.mode == "setup" else "save",
                "count": "name" if a["count"] else "other",
                "dir": "local_repo" if len(a["repos"]) > 1 else registering,
                "other": "ssh" if a["other"] else "approval",
                "approval": "workflows" if a["approval"] else "command"}[step]

    def check(self, step, value):
        """(error, warning, the value as it is kept)"""
        a = self.answers
        if step == "repos":
            repos = [r.strip() for r in value.split(",") if r.strip()]
            if not repos:
                return "Write at least one repository, like owner/name.", None, None
            for repo in repos:
                if not SLUG.match(repo):
                    return f"{repo} is not like owner/name.", None, None
            repos = list(dict.fromkeys(repos))
            seen = [self.checks.repo(repo) for repo in repos]
            for repo, ok in zip(repos, seen):
                if ok is False:
                    return f"gh cannot see {repo}. Check the name, and that you may read it.", None, None
            return None, ("gh is not available, so the names are not checked. Press Enter again to go on."
                          if None in seen else None), repos
        if step == "count":
            if not re.fullmatch(r"[0-9]", value):
                return "Write a number from 0 to 9.", None, None
            return None, None, int(value)
        if step == "name":
            if not WORD.match(value) or " " in value:
                return "Use letters, digits, dots, dashes and underscores. No spaces.", None, None
        if step == "dir" and not value:
            return "Write a folder.", None, None
        if step == "local_repo" and value not in a["repos"]:
            return "Choose one of: " + ", ".join(a["repos"]), None, None
        if step == "token" and value and not TOKEN.match(value):
            return "That is not a token: letters and digits only.", None, None
        if step == "ssh":
            if not HOST.match(value):
                return "Write it like user@host.", None, None
            a["host_name"] = re.sub(r"[^A-Za-z0-9_-]", "", value.split("@")[-1].split(".")[0]) or "pc"
            tried = self.checks.ssh(value)
            connected, why = tried if isinstance(tried, tuple) else (tried, "It did not connect.")
            if not connected:
                return None, why + " Press Enter again to keep the address anyway.", value
        if step == "service" and value and not HOST.match(value):
            return "Write a service name, like actions-runner.service. Or leave it empty.", None, None
        if step == "workflows":
            names = [w.strip() for w in value.split(",") if w.strip()]
            if (not names and self.mode == "setup") or not all(WORD.match(w) for w in names):
                return "Write the workflow names, with a comma between them.", None, None
            return None, None, names
        if step == "label" and not WORD.match(value):
            return "Use letters, digits, dots, dashes and underscores.", None, None
        return None, None, value

    # ---- the end
    def write(self):
        text = config_text(self.answers)
        parser = configparser.ConfigParser()
        parser.read_string(text)
        try:
            cfg = configure(parser)
        except ConfigError as err:
            self.note, self.bad = str(err), True
            return
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            if os.path.exists(self.path):
                shutil.copyfile(self.path, self.path + ".bak")
            with open(self.path, "w") as file:
                file.write(text)
        except OSError as err:
            self.note, self.bad = f"Cannot write {self.path}: {err}", True
            return
        self.cfg = cfg
        if self.answers["command"] and self.install:
            try:
                self.installed = self.install()
            except OSError as err:
                self.problem = f"The runnerdeck command was not made: {err}"
        self.go("work" if self.answers["count"] else "done")

    def work(self):
        """The runners, one after the other, while the screen shows how far it is."""
        cfg, a = self.cfg, self.answers
        # A token is needed only for a runner that is not set up yet.
        missing = [n for n in range(1, a["count"] + 1) if not Runner(cfg, n).configured]
        token = (a["token"] or gh_token(cfg)) if missing else None
        if missing and not token:
            self.progress.append(("bad", "No token. Press n on the main screen later to add the runners."))
        else:
            for n in range(1, a["count"] + 1):
                name = Runner(cfg, n).name
                self.progress.append(("dim", f"… {name}: " + ("starting" if Runner(cfg, n).configured
                                                              else "download and register (this takes a minute)")))
                try:
                    ready = Runner(cfg, n).configured
                    self.make(cfg, n, token)
                    self.progress[-1] = ("good", f"✓ {name} is running" + (" (it was set up already)" if ready else ""))
                except (OSError, subprocess.SubprocessError) as err:
                    self.progress[-1] = ("bad", f"✗ {name}: {err}")
        self.working = False

    # ---- what the screen draws
    def text(self):
        a, step = self.answers, self.step
        ok, signed = self.gh
        if step == "welcome" and self.busy:
            return []
        if step == "welcome":
            lines = ["This asks a few questions and writes the config file. Nothing changes until the last step.", "",
                     ("good", "✓ Python " + platform.python_version())]
            if signed:
                lines.append(("good", "✓ gh is installed and you are signed in"))
            elif ok:
                lines.append(("bad", "✗ gh is installed, but you are not signed in. Run: gh auth login"))
            else:
                lines.append(("bad", "✗ gh is not installed. Get it from https://cli.github.com"))
            if self.found:
                lines += ["", ("good", f"✓ I found {len(self.found)} runner(s) on this machine:")]
                lines += [("plain", f"   {item['name']}  {item['dir']}  {item['repo']}") for item in self.found]
                if self.plan:
                    lines += [("dim", "   The next questions offer them, so you only press Enter.")]
                if self.left:
                    lines += [("warm", "   The program cannot manage these: " + ", ".join(item["name"] for item in self.left)
                                       + ". They need a name and a folder like name, name-2, and folder, folder-2.")]
            if not signed:
                lines += ["", "You can go on, but the program cannot show the runs until gh works."]
            return lines
        return {
            "repos": ["Which repository do you want to watch?", "Write owner/name. Use a comma for more than one."],
            "count": ["How many runners do you want on this machine?",
                      ("I found " + str(self.plan["count"]) + " set up here. Keep the number to use them."
                       if self.plan else "0 means none: you only watch.")],
            "name": ["What name do the runners get?", f"They are called {a['name']}, {a['name']}-2, {a['name']}-3 and so on."],
            "dir": ["In which folder do the runners live?", "The second runner gets the same name with -2 after it."],
            "local_repo": ["For which repository are the new runners?"],
            "token": ["Paste the registration token. It is for the runners that are not set up yet.", "Get it here: Settings > Actions > Runners > New self-hosted runner.",
                      "Leave it empty to ask gh. This works only if you are an admin of the repository.",
                      "The token is shown as dots and is not saved."],
            "other": ["Do you also want to see a second computer on this screen?",
                      "For example your Linux PC, while this runs on your Mac. It must run Linux for now. The program only reads from it.",
                      "If you are not sure, answer n. You can add it later in the config file."],
            "ssh": ["What is the SSH address of the machine?", "For example: me@my-pc. It must work with a key, without a password."],
            "service": ["What is the name of the runner service on that machine?",
                        "For example: actions-runner.service. Leave it empty if it has none."],
            "approval": ["Do you want to keep a workflow behind your approval?",
                         "Some workflows should start only when you say yes. A deploy or a TestFlight upload is an example.",
                         "If you have none, answer n. You can add one later."],
            "workflows": self.pick_text() if self.options else [
                          "Which workflow must wait for your yes?",
                          "gh did not list any, so write the name as GitHub shows it in the Actions tab. For example: TestFlight.",
                          "Use a comma for more than one."],
            "label": ["Which label do the requests have?",
                      "To ask for a start, a person or a tool opens an issue with this label."]
                     + (["On GitHub these labels look like requests: " + ", ".join(
                         [name for name in self.labels if "request" in name.lower()][:6])]
                        if any("request" in name.lower() for name in self.labels) else [])
                     + [
                      "The title of the issue is the workflow name, a branch and a commit. For example: "
                      + (a["workflows"] or ["Deploy"])[0] + ": main a0d3a70"],
            "save": (["Saved.", "", "These workflows wait for your yes: " + (", ".join(a["workflows"]) or "none"),
                     f"The old file is kept as {os.path.basename(self.path)}.bak."] if self.saved else ["The file was not changed."]),
            "command": ["Do you want a `runnerdeck` command in your terminal?",
                        "The program copies itself to your home folder (runnerdeck.pyz) and adds one line to your shell file."],
            "review": ["This is the config file:", ""] + config_text(a).split("\n# ---- ")[0].splitlines()
                      + ["", "At the foot it lists all other options, as comments.", f"Enter writes it to {self.path}"]
                      + ([f"The old file is kept as {os.path.basename(self.path)}.bak"] if os.path.exists(self.path) else []),
            "work": [] + [item for item in self.progress] + ([] if self.working else ["", "Press Enter."]),
            "done": ["Setup is done.", ""] + ([("good", item) for item in (self.installed or "").splitlines()] if self.installed
                                               else ["Start the program again with: python3 -m runnerdeck"])
                    + ([("bad", self.problem)] if self.problem else [])
                    + ["", f"Your config file is {self.path}", "Read it with: cat " + self.path, self.open_tip()],
        }[step]

    def pick_text(self):
        """The list: ten at a time around the cursor, [x] for what is chosen."""
        rows = ["Which workflows must wait for your yes?",
                "Move with the arrow keys. Press the space bar to choose. Press Enter when you are done.", ""]
        start = max(0, min(self.cursor - 4, len(self.options) - 10))
        for i in range(start, min(len(self.options), start + 10)):
            mark = "x" if i in self.picked else " "
            rows.append(("strong" if i == self.cursor else "plain", f"{'›' if i == self.cursor else ' '} [{mark}] {self.options[i]}"))
        if len(self.options) > 10:
            rows.append(("dim", f"   {len(self.options)} workflows. The arrow keys show more."))
        if self.skipped:
            rows.append(("warm", f"   {self.skipped} more have names with characters the program cannot use."))
        return rows

    def open_tip(self):
        """How to open the file in the file manager of this system."""
        if platform.system() == "Darwin":
            return "Or show it in Finder: open -R " + self.path
        if platform.system() == "Windows":
            return "Or show it in Explorer: explorer /select," + self.path
        return "Or open its folder: xdg-open " + os.path.dirname(self.path)

    def view(self):
        kind, title = self.kind(), STEPS[self.step][1]
        hint = {"info": "enter: next · esc: back", "text": "enter: next · esc: back",
                "yesno": f"y: yes · n: no · enter: {'yes' if self.default(self.step) == 'y' else 'no'} · esc: back",
                "pick": "↑ ↓: move · space: choose · enter: next · esc: back"}[kind]
        if self.step == "work" and self.working:
            hint = "wait…"
        if self.step == "done":
            hint = "enter: open the screen"
        if self.step == "save":
            hint = "enter: back to the screen · esc: back"
        busy = (self.SPINNER[int(time.time() * 10) % len(self.SPINNER)] + " " + self.busy) if self.busy else None
        if busy:
            hint = "esc: stop waiting"
        return {"title": title, "lines": [] if self.hide else self.text(),
                "field": self.field if kind == "text" and not self.hide else None, "busy": busy,
                "secret": self.step == "token", "fresh": self.fresh, "hint": hint, "note": self.note, "bad": self.bad}


def draw(canvas, view):
    """One question, in a frame in the middle."""
    width = min(canvas.width - 2, 78)
    inner = max(10, width - 6)
    rows = []
    for item in view["lines"]:
        style, text = item if isinstance(item, tuple) else ("plain", item)
        rows += [(style, piece) for piece in (textwrap.wrap(text, inner) or [""])]
    if view["field"] is not None:
        shown = ("●" * len(view["field"])) if view["secret"] else view["field"]
        rows += [("plain", ""), ("dim" if view["fresh"] else "strong", "› " + shown[-(inner - 4):] + "▏")]
    if view["busy"]:
        rows += [("plain", ""), ("warm", view["busy"])]
    if view["note"]:
        rows += [("plain", "")] + [("bad" if view["bad"] else "warm", piece) for piece in textwrap.wrap(view["note"], inner)]
    height = min(canvas.height, len(rows) + 5)
    x, y = (canvas.width - width) // 2, max(0, (canvas.height - height) // 2)
    frame(canvas, y, x, height, width, "runnerdeck · setup", view["title"])
    for at, (style, text) in enumerate(rows[:height - 4], start=y + 2):
        canvas.put(at, x + 3, text, style)
    canvas.put(y + height - 2, x + 3, view["hint"][:inner], "label")


def run(terminal, wizard):
    """The wizard on the terminal, until it is done or stopped. The config, or None."""
    colours()
    while not wizard.finished:
        wizard.tick()
        canvas = Screen(terminal)
        draw(canvas, wizard.view())
        canvas.flush()
        # Quick while something turns on the screen, slow when it waits for a key.
        key = terminal.key(0.1 if wizard.busy or wizard.working else 1.0)
        if key == K_RESIZE:
            sys.stdout.buffer.write(b"\x1b[2J")
        elif key != -1:
            wizard.feed(key)
    return None if wizard.cancelled else wizard.cfg
