#!/usr/bin/env python3
"""python3 tests/test_runnerdeck.py — config, requests, the machine's answer, the screen, one file."""
import configparser
import os
import re
import stat
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# The records of builds that the screen reads are the test's own, never those of whoever runs it.
os.environ["RUNNERDECK_DATA"] = tempfile.mkdtemp(prefix="runnerdeck-data-")
sys.path.insert(0, ROOT)
from runnerdeck import boxes, builds, config as configmod, github, machines, runners, system, terminal


def configured(text):
    config = configparser.ConfigParser()
    config.read_string(text)
    return configmod.configure(config)


def active(text):
    """A config file without the list of all options that the program writes at its foot."""
    return text.split("\n# ---- ", 1)[0].rstrip("\n") + "\n"


def refuses(text, word):
    try:
        configured(text)
    except configmod.ConfigError as err:
        assert word in str(err), (word, str(err))
        return
    raise AssertionError(f"accepted: {text!r}")


# --- config: what reaches gh, ssh or a file name has to look like what it is
cfg = configured("[deck]\nrepos = a/b, c/d\n[approval]\nworkflows = Deploy, Ship it\nlabel = ask\n")
assert cfg.repos == ["a/b", "c/d"] and cfg.local is None and cfg.hosts == []
refuses("", "empty")
refuses("[deck]\nrepos = a/b/c\n", "not a repository")
refuses("[deck]\nrepos = --repo=x/y\n", "not a repository")
refuses("[deck]\nrepos = a/b\n[host pc]\nssh = -oProxyCommand=x\n", "ssh = user@host")
refuses("[deck]\nrepos = a/b\n[host pc]\nssh = u@h\nservice = a b\n", "service")
refuses("[deck]\nrepos = a/b\n[local]\nrepo = x/y\n", "not in [deck]")
refuses("[deck]\nrepos = a/b\n[approval]\nworkflows = Deploy\n", "label")
refuses("[deck]\nrepos = a/b\n[approval]\nworkflows = -x\nlabel = ask\n", "label")

# --- requests: a workflow of the list, a branch, a commit; and nothing else
cfg = configured("[deck]\nrepos = a/b, c/d\n[approval]\nworkflows = Deploy, Ship it\nlabel = ask\n")
good = github.asked(cfg, {"number": 1, "title": "Deploy: feature-x a0d3a70", "body": "Mask lag\nmore"}, "a/b", 0)
assert (good["workflow"], good["branch"], good["sha"], good["note"], good["repo"]) == ("Deploy", "feature-x", "a0d3a70", "Mask lag", "a/b")
assert github.asked(cfg, {"number": 1, "title": "Ship it: main a0d3a70"}, "a/b", 0)["workflow"] == "Ship it"
for title in ("Deploy: --repo=other a0d3a70", "Deploy: main", "Deploy: main xyz", "Run Deploy: main a0d3a70",
              "Deploy: a b a0d3a70", "Deploy: main a0d3a70; rm", "Other: main a0d3a70"):
    assert github.asked(cfg, {"number": 2, "title": title}, "a/b", 0) is None, title
# The same issue number in two repositories is two rows, and neither is a run's.
one, two = (github.asked(cfg, {"number": 7, "title": "Deploy: m a0d3a70"}, repo, index) for index, repo in enumerate(("a/b", "c/d")))
assert one["row"] < 0 and two["row"] < 0 and one["row"] != two["row"]
cfg = configured("[deck]\nrepos = a/b\n")
assert github.asked(cfg, {"number": 3, "title": "Deploy: main a0d3a70"}) is None  # nothing waits where nothing is gated

# --- a machine's answer: busy is all but idle and iowait over the second between the reads
said = """stat cpu  100 0 100 700 100 0 0 0 0 0
stat cpu  200 0 200 750 150 0 0 0 0 0
load 1.52
threads 16
mem_MemTotal 33554432
mem_MemAvailable 16777216
gpu 37
vram_used 4294967296
vram_total 17179869184
gpu_temp 58000
gpu_power 142000000
cpu_temp 71250
runner active
log
2026-10-30 18:11:09Z: Listening for Jobs
2026-10-30 18:12:00Z: Running job: check\x1b[2J
"""
now = machines.parse_pc(said)
assert round(now["cpu"]) == 67, now["cpu"]
assert now["memory"] == (16.0, 32.0) and now["vram"] == (4.0, 16.0)
assert (now["gpu"], now["gpu_temp"], now["gpu_power"], now["cpu_temp"]) == (37, 58, 142, 71.25)
assert now["log"][-1] == "2026-10-30 18:12:00Z: Running job: check[2J"  # no escape reaches the screen
assert runners.said_by(now["log"])[:2] == ("running", "check[2J")
assert machines.parse_pc("threads x\ngpu_temp \nlog\n")["gpu_temp"] is None
assert machines.parse_pc("")["cpu"] is None and machines.parse_pc("")["memory"] is None
assert machines.ask_pc("-oProxyCommand=x") is None and machines.ask_pc("pc", "a b") is None

# --- NVIDIA's line, and the AMD files first
assert machines.parse_nvidia("37, 58, 142.30, 4096, 16384") == {"gpu": 37.0, "gpu_temp": 58.0, "gpu_power": 142.3, "vram": (4.0, 16.0)}
assert machines.parse_nvidia("[N/A], 58, [N/A], 4096, 16384") == {"gpu_temp": 58.0, "vram": (4.0, 16.0)}
assert machines.parse_nvidia("") == {} and machines.parse_nvidia("a, b") == {}
both = machines.parse_pc("gpu 10\nnvidia 90, 70, 200, 1024, 2048\nlog\n")
assert both["gpu"] == 10 and both["gpu_temp"] == 70 and both["vram"] == (1.0, 2.0)  # AMD's where it spoke, NVIDIA's for the rest

# --- the runner's download, by platform
import platform
real_platform = platform.system, platform.machine
for os_name, arch, ending in (("Darwin", "arm64", "osx-arm64-%s.tar.gz"), ("Linux", "x86_64", "linux-x64-%s.tar.gz"),
                                ("Linux", "aarch64", "linux-arm64-%s.tar.gz"), ("Windows", "AMD64", "win-x64-%s.zip"),
                                ("Windows", "ARM64", "win-arm64-%s.zip")):
    platform.system, platform.machine = (lambda v=os_name: v), (lambda v=arch: v)
    assert system.release(cfg.version).endswith("actions-runner-" + ending % cfg.version), (os_name, arch, system.release(cfg.version))
platform.system, platform.machine = (lambda: "Plan9"), (lambda: "mips")
try:
    system.release(cfg.version)
    raise AssertionError("a platform with no runner")
except OSError:
    pass
platform.system, platform.machine = real_platform  # back to the real ones

# --- the keys are curses' own numbers, so that Windows can say the same
if terminal.curses:
    assert (terminal.K_UP, terminal.K_DOWN, terminal.K_LEFT, terminal.K_RIGHT, terminal.K_ENTER, terminal.K_RESIZE, terminal.K_BACKSPACE) == (
        terminal.curses.KEY_UP, terminal.curses.KEY_DOWN, terminal.curses.KEY_LEFT, terminal.curses.KEY_RIGHT,
        terminal.curses.KEY_ENTER, terminal.curses.KEY_RESIZE, terminal.curses.KEY_BACKSPACE)

# --- it loads where there is no curses, as on Windows
out = subprocess.run([sys.executable, "-c", "import sys; sys.modules['curses'] = None; sys.path.insert(0, %r); "
                      "import runnerdeck.app, runnerdeck.terminal; assert runnerdeck.terminal.curses is None" % ROOT], capture_output=True, text=True)
assert out.returncode == 0, out.stderr

# --- a new runner from a pasted token: what is refused, and what is made
cfg = configured("[deck]\nrepos = a/b\n[local]\nname = box\ndir = %s\ncount = 2\n" % os.path.join(tempfile.gettempdir(), "runner-test-dir"))
made = []
assert runners.add_runner(cfg, made, "x; rm -rf /")[1] is False
assert runners.add_runner(cfg, made, "short")[1] is False
assert runners.add_runner(cfg, made, "has space in it 12345")[1] is False and made == []
real = (runners.set_up, runners.Runner.start, runners.gh_token)
calls = []
runners.set_up = lambda cfg, runner, token, quiet=False: calls.append((runner.name, token, quiet))
runners.Runner.start = lambda self: calls.append(("start", self.name))
runners.gh_token = lambda cfg: None
said, went = runners.add_runner(cfg, made, "")
assert not went and "paste" in said and made == []  # no token and gh cannot: it says where to get one
said, went = runners.add_runner(cfg, made, "  AABBCCDDEEFF1122  ")
assert went and said == "box is up" and [r.name for r in made] == ["box"], (said, made)
assert calls == [("box", "AABBCCDDEEFF1122", True), ("start", "box")], calls
runners.gh_token = lambda cfg: "FROMGH12345"
assert runners.add_runner(cfg, made, "")[1] and [r.name for r in made] == ["box", "box-2"] and calls[-2][1] == "FROMGH12345"
runners.set_up = lambda *a, **k: (_ for _ in ()).throw(OSError("boom"))
said, went = runners.add_runner(cfg, made, "AABBCCDDEEFF1122")
assert not went and "boom" in said and len(made) == 2  # a failed one is not in the list
runners.set_up, runners.Runner.start, runners.gh_token = real

if system.WINDOWS:
    # What only Windows can say: its processes and its readings.
    assert system.exists(os.getpid()) and not system.exists(2**22 + 12345)
    mine = machines.windows_here()
    assert mine["memory"] and mine["memory"][1] > 0 and mine["threads"] > 0
    assert mine["cpu"] is None or 0 <= mine["cpu"] <= 100, mine["cpu"]
    assert "creationflags" in system.apart()
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], **system.apart())
    pidfile = os.path.join(tempfile.gettempdir(), "runner-test.pid")
    system.write(pidfile, child.pid)
    assert system.alive(pidfile) == child.pid
    system.end(pidfile)
    child.wait(timeout=20)
    assert system.alive(pidfile) is None
else:
    # --- the real script, here: it answers on a machine with no GPU, no unit and no ssh
    if sys.platform.startswith("linux"):
        here = machines.ask_pc(None, "")
        assert here and here["threads"] and here["memory"] and here["log"] == []

    # --- the whole screen, once, with a stand-in ssh that runs what it is sent here
    with tempfile.TemporaryDirectory() as tmp:
        ssh = os.path.join(tmp, "ssh")
        with open(ssh, "w") as file:
            file.write('#!/bin/sh\nwhile [ "$1" != "--" ]; do shift; done; shift; shift; exec "$@"\n')
        os.chmod(ssh, os.stat(ssh).st_mode | stat.S_IEXEC)
        # No network in a test: a gh that has nothing to say.
        gh = os.path.join(tmp, "gh")
        with open(gh, "w") as file:
            file.write("#!/bin/sh\nexit 1\n")
        os.chmod(gh, os.stat(gh).st_mode | stat.S_IEXEC)
        config = os.path.join(tmp, "config.ini")
        with open(config, "w") as file:
            file.write("[deck]\nrepos = a/b\n[host workstation]\nssh = me@box\nservice = runner.service\n")
        env = dict(os.environ, PATH=tmp + os.pathsep + os.environ["PATH"], RUNNERDECK_CONFIG=config, RUNNERDECK_HOME=tmp)
        out = subprocess.run([sys.executable, "-m", "runnerdeck", "--status"], env=env, cwd=ROOT,
                             capture_output=True, text=True, timeout=60)
        assert out.returncode == 0, out.stderr
        assert "workstation" in out.stdout and "box" in out.stdout and "◐ runnerdeck" in out.stdout, out.stdout
        # No config: it says what to do, and does not draw.
        env["RUNNERDECK_CONFIG"] = os.path.join(tmp, "none.ini")
        out = subprocess.run([sys.executable, "-m", "runnerdeck", "--status"], env=env, cwd=ROOT, capture_output=True, text=True)
        assert out.returncode != 0 and "--init" in out.stderr, out.stderr
        # --init writes an example that is itself a valid config, and does not overwrite.
        out = subprocess.run([sys.executable, "-m", "runnerdeck", "--init"], env=env, cwd=ROOT, capture_output=True, text=True)
        assert out.returncode == 0 and os.path.exists(env["RUNNERDECK_CONFIG"]), out.stderr
        cfg = configured(open(env["RUNNERDECK_CONFIG"]).read())
        assert cfg.repos == ["owner/name"] and cfg.local is None      # watch only: an example must not set up runners


    assert "creationflags" not in system.apart() and system.exists(os.getpid()) and not system.exists(2**22 + 12345)

# --- the program was called runner first: an old config or variable is still found, a new one wins
with tempfile.TemporaryDirectory() as home:
    saved = {key: os.environ.get(key) for key in ("HOME", "RUNNERDECK_CONFIG", "RUNNER_CONFIG")}
    try:
        os.environ["HOME"] = home
        os.environ.pop("RUNNERDECK_CONFIG", None)
        os.environ.pop("RUNNER_CONFIG", None)
        new_file, old_file = (os.path.join(home, ".config", name, "config.ini") for name in ("runnerdeck", "runner"))
        assert configmod.default_path() == new_file                      # nothing there yet: where a new one goes
        os.makedirs(os.path.dirname(old_file))
        open(old_file, "w").write("[deck]\nrepos = a/b\n")
        assert configmod.default_path() == old_file                      # only the old one: it is used, the setup does not start
        assert configmod.load().repos == ["a/b"]
        os.makedirs(os.path.dirname(new_file))
        open(new_file, "w").write("[deck]\nrepos = c/d\n")
        assert configmod.default_path() == new_file                      # both: the new one wins
        os.environ["RUNNER_CONFIG"] = "/old/variable.ini"
        assert configmod.default_path() == "/old/variable.ini"           # the old variable still works
        os.environ["RUNNERDECK_CONFIG"] = "/new/variable.ini"
        assert configmod.default_path() == "/new/variable.ini"           # and the new one is first
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

# --- the config examples in the documents are valid, so they cannot drift
import glob
blocks = 0
for path in glob.glob(os.path.join(ROOT, "README.md")) + glob.glob(os.path.join(ROOT, "docs", "*.md")):
    for block in re.findall(r"```ini\n(.*?)```", open(path, encoding="utf-8").read(), re.S):
        text = block if "[deck]" in block else "[deck]\nrepos = a/b\n" + block
        text = text.replace("[local]\n", "[local]\n") if "[local]" not in text else text
        configured(text)
        blocks += 1
assert blocks >= 6, blocks  # the examples in the README and in docs/config.md

# --- the first start: the questions, fed keys, with stand-ins for gh, ssh and the downloads
from runnerdeck import setup as setupmod


class Checks:
    def __init__(self, gh=(True, True), seen=None, ssh=True, workflows=None, labels=None):
        self.gh_state, self.seen, self.ssh_ok, self.names = gh, seen or {}, ssh, workflows or {}
        self.label_names = labels or {}

    def labels(self, repo):
        return self.label_names.get(repo, [])

    def workflows(self, repo):
        return self.names.get(repo, [])

    def gh(self):
        return self.gh_state

    def repo(self, repo):
        return self.seen.get(repo, True)

    def ssh(self, host):
        return self.ssh_ok, "" if self.ssh_ok else "The PC refuses the connection."


def wipe_and_type(wizard, text):
    for _ in range(len(wizard.field)):
        wizard.feed(127)
    for letter in text:
        wizard.feed(ord(letter))


def answer(wizard, text=None):
    if text is not None:
        wipe_and_type(wizard, text)
    wizard.feed(13)


with tempfile.TemporaryDirectory() as tmp:
    made, installed = [], []
    path = os.path.join(tmp, "conf", "config.ini")

    def wizard_for(**kinds):
        return setupmod.Wizard(Checks(**kinds), threaded=False, install=lambda: installed.append(1) or "Open a new terminal.\nType: runner",
                               make=lambda cfg, n, token: made.append((cfg.local["name"], n, token)), path=path)

    # the whole way, with every question answered
    runner_dir = os.path.join(tmp, "r")
    w = wizard_for()
    assert w.step == "welcome" and w.gh == (True, True)
    answer(w)
    answer(w, "a/b, c/d")
    answer(w, "2")
    answer(w, "box")
    answer(w, runner_dir)                       # the folder: none of the runners is there yet
    answer(w)                                   # the repository of the runners: the first
    answer(w, "ABCDEFGH12345")
    w.feed(ord("y"))                            # another machine
    answer(w, "me@my-pc")
    answer(w, "x.service")
    w.feed(ord("y"))                            # approval
    answer(w, "Deploy")
    answer(w)                                   # the label: deploy-request
    w.feed(ord("y"))                            # the command
    assert w.step == "review" and "[host my-pc]" in "\n".join(map(str, w.text()))
    answer(w)
    assert w.step == "work"
    for _ in range(200):
        if not w.working:
            break
        time.sleep(0.05)
    assert made == [("box", 1, "ABCDEFGH12345"), ("box", 2, "ABCDEFGH12345")], made
    answer(w)
    assert w.step == "done" and installed == [1]
    answer(w)
    assert w.finished and not w.cancelled and w.cfg.repos == ["a/b", "c/d"]
    written = open(path).read()
    assert active(written) == ("[deck]\nrepos = a/b, c/d\n\n[local]\nname = box\ndir = " + runner_dir + "\ncount = 2\nrepo = a/b\n\n"
                       "[host my-pc]\nssh = me@my-pc\nservice = x.service\n\n[approval]\nworkflows = Deploy\nlabel = deploy-request\n"), written
    # every file the program writes lists all the options at its foot, as comments
    for section in ("[deck]", "[local]", "[host pc]", "[approval]", "[names]"):
        assert "\n# " + section + "\n" in written, section
    for option in ("repos", "name", "dir", "count", "repo", "version", "keychain", "ssh", "service", "workflows", "label"):
        assert "\n# " + option + " = " in written, option
    assert "\n# [approval]\n" in written and configmod.load(path).approval["label"] == "deploy-request"
    # the key w changes only the approval section: the list at the foot is left as it is
    configmod.set_approval(path, ["Ship it"], "ship-request")
    after = open(path).read()
    assert "\nworkflows = Ship it" in active(after) and "workflows = Deploy" not in active(after)
    assert after.split("\n# ---- ", 1)[1] == written.split("\n# ---- ", 1)[1]
    configmod.set_approval(path, [], "")
    assert "[approval]\n" not in active(open(path).read()) and open(path).read().split("\n# ---- ", 1)[1] == written.split("\n# ---- ", 1)[1]
    open(path, "w").write(written)                                              # as it was, for what follows
    assert "ABCDEFGH12345" not in written and configmod.load(path).local["count"] == 2   # the token is not kept

    # what is offered goes at the first key typed; backspace edits it instead
    w = wizard_for()
    answer(w); answer(w, "a/b")
    assert w.step == "count" and w.field == "0" and w.view()["fresh"]
    w.feed(ord("2"))
    assert w.field == "2" and not w.view()["fresh"]
    w.feed(127)
    assert w.field == ""
    answer(w, "0")
    w = wizard_for()
    answer(w); answer(w, "a/b"); answer(w, "1")
    assert w.step == "name" and w.field
    shown = w.field
    w.feed(127)
    assert w.field == shown[:-1]

    # the workflows are listed, and chosen with the arrow keys and the space bar
    names = ["CI", "Build", "TestFlight", "Screenshots", "Feedback", "Bad & Name", "Nightly", "Docs", "Lint", "Smoke",
             "Release", "Deploy"]
    w = wizard_for(workflows={"a/b": names[:8], "c/d": names[6:]})
    answer(w); answer(w, "a/b, c/d"); answer(w, "0"); w.feed(ord("n")); w.feed(ord("y"))
    assert w.step == "workflows" and w.kind() == "pick"
    assert w.options == ["CI", "Build", "TestFlight", "Screenshots", "Feedback", "Nightly", "Docs", "Lint", "Smoke", "Release", "Deploy"]
    assert w.skipped == 1                                                    # "Bad & Name": the program cannot use it
    shown = "\n".join(str(row) for row in w.text())
    assert "[ ] CI" in shown and "11 workflows" in shown and "cannot use" in shown
    answer(w)                                                                # nothing chosen yet
    assert w.step == "workflows" and w.bad
    w.feed(terminal.K_DOWN); w.feed(terminal.K_DOWN); w.feed(32)             # TestFlight
    w.feed(terminal.K_UP); w.feed(terminal.K_UP); w.feed(terminal.K_UP)      # stays at the top
    assert w.cursor == 0
    w.feed(32)                                                               # CI
    w.feed(32)                                                               # CI off again
    for _ in range(20):
        w.feed(terminal.K_DOWN)
    assert w.cursor == 10                                                    # stops at the last
    w.feed(32)                                                               # Deploy
    answer(w)
    assert w.step == "label" and w.answers["workflows"] == ["TestFlight", "Deploy"] and w.field == "testflight-request"
    w.feed(27)                                                               # back: what was chosen is still chosen
    assert w.step == "workflows" and w.picked == {2, 10}
    w.feed(27); w.feed(27)
    assert w.step == "other"

    # the example in the question names the workflow that was chosen
    w = wizard_for(workflows={"a/b": ["Build", "TestFlight"]})
    answer(w); answer(w, "a/b"); answer(w, "0"); w.feed(ord("n")); w.feed(ord("y"))
    w.feed(terminal.K_DOWN); w.feed(32); answer(w)
    assert w.step == "label" and w.field == "testflight-request" and "TestFlight: main a0d3a70" in str(w.text())
    w.feed(27); w.feed(terminal.K_UP); w.feed(32); w.feed(terminal.K_DOWN); w.feed(32)   # Build on, TestFlight off
    answer(w)
    assert w.field == "build-request" and "Build: main a0d3a70" in str(w.text())

    # the label offered is one that is on GitHub already and fits a chosen workflow
    def label_for(labels, picks):
        w = wizard_for(workflows={"a/b": ["Build", "CI", "TestFlight"]}, labels={"a/b": labels})
        answer(w); answer(w, "a/b"); answer(w, "0"); w.feed(ord("n")); w.feed(ord("y"))
        for index in picks:
            while w.cursor < index:
                w.feed(terminal.K_DOWN)
            w.feed(32)
        answer(w)
        assert w.step == "label"
        return w

    w = label_for(["bug", "testflight-request"], [0, 1, 2])                  # Build, CI and TestFlight chosen
    assert w.field == "testflight-request" and "testflight-request" in " ".join(map(str, w.text()))
    assert label_for([], [0, 1]).field == "build-request"                    # nothing on GitHub: from the first
    assert label_for(["build-request", "testflight-request"], [0, 2]).field == "build-request"   # the first one's own label wins
    assert label_for(["release-request", "Test-Flight request"], [2]).field == "testflight-request"
    assert label_for(["ci-request"], [1]).field == "ci-request"
    assert label_for(["special-request"], [1]).field == "ci-request"         # ci is not a word of special-request

    # no list from gh: the names are typed, as before
    w = wizard_for()
    answer(w); answer(w, "a/b"); answer(w, "0"); w.feed(ord("n")); w.feed(ord("y"))
    assert w.step == "workflows" and w.kind() == "text" and "did not list any" in str(w.text())
    answer(w, "TestFlight, Build")
    assert w.step == "label" and w.answers["workflows"] == ["TestFlight", "Build"]

    # the approval section alone: set, replaced, taken out; the rest of the file as it was
    original = ("# my runners\n[deck]\nrepos = a/b\n\n# the PC\n[host pc]\nssh = me@pc\nservice = x.service\n")
    plain = os.path.join(tmp, "edit.ini")
    open(plain, "w").write(original)
    configmod.set_approval(plain, ["Deploy", "Ship it"], "ask")
    assert open(plain).read() == original + "\n[approval]\nworkflows = Deploy, Ship it\nlabel = ask\n"
    assert open(plain + ".bak").read() == original
    with_comments = ("[deck]\nrepos = a/b\n\n# a start is yours\n[approval]\nworkflows = Old\nlabel = old-request\n\n"
                     "# the jobs\n[names]\nbuild = Build\n")
    open(plain, "w").write(with_comments)
    configmod.set_approval(plain, ["TestFlight"], "testflight-request")
    assert open(plain).read() == ("[deck]\nrepos = a/b\n\n# a start is yours\n[approval]\nworkflows = TestFlight\n"
                                  "label = testflight-request\n\n# the jobs\n[names]\nbuild = Build\n"), open(plain).read()
    configmod.set_approval(plain, [], "")
    assert "[approval]" not in open(plain).read() and "[names]\nbuild = Build" in open(plain).read()
    assert configmod.load(plain).approval == {"workflows": [], "label": ""}
    before = open(plain).read()
    try:
        configmod.set_approval(plain, ["Bad & Name"], "ask")
        raise AssertionError("a name the program cannot use")
    except configmod.ConfigError:
        pass
    assert open(plain).read() == before                                       # put back as it was

    # the same questions again, for a config that is there: what is set is chosen to begin with
    cfg_now = configured("[deck]\nrepos = a/b\n[approval]\nworkflows = TestFlight\nlabel = testflight-request\n")
    open(plain, "w").write("[deck]\nrepos = a/b\n[approval]\nworkflows = TestFlight\nlabel = testflight-request\n")
    w = setupmod.Wizard.for_approval(cfg_now, Checks(workflows={"a/b": ["CI", "Build", "TestFlight"]}), path=plain, threaded=False)
    assert w.step == "workflows" and w.kind() == "pick" and w.picked == {2}
    w.feed(32)                                                                 # CI on as well
    answer(w)
    assert w.step == "label" and w.field == "testflight-request"
    answer(w)
    assert w.step == "save" and w.saved
    assert configmod.load(plain).approval == {"workflows": ["CI", "TestFlight"], "label": "testflight-request"}
    answer(w)
    assert w.finished and not w.cancelled
    w = setupmod.Wizard.for_approval(cfg_now, Checks(workflows={"a/b": ["CI", "TestFlight"]}), path=plain, threaded=False)
    w.feed(terminal.K_DOWN); w.feed(32)                                        # TestFlight off: none wait
    answer(w)
    assert w.step == "save" and w.saved and configmod.load(plain).approval == {"workflows": [], "label": ""}
    w = setupmod.Wizard.for_approval(cfg_now, Checks(workflows={"a/b": ["CI"]}), path=plain, threaded=False)
    w.feed(27)
    assert w.finished and w.cancelled and not w.saved                          # escape at the start changes nothing

    # a computer is added to the config: its section only, the rest of the file as it was
    hosted = os.path.join(tmp, "hosts.ini")
    base = "# mine\n[deck]\nrepos = a/b\n\n# the jobs\n[names]\nbuild = Build\n"
    open(hosted, "w").write(base + "\n" + configmod.REFERENCE)
    configmod.set_host(hosted, "pc", "me@192.168.2.15", "x.service")
    after = open(hosted).read()
    assert "[deck]\nrepos = a/b\n\n# the jobs\n[names]\nbuild = Build\n\n[host pc]\nssh = me@192.168.2.15\nservice = x.service\n" in after
    assert after.endswith(configmod.REFERENCE) or after.split("\n# ---- ", 1)[1] == configmod.REFERENCE.split("# ---- ", 1)[1]
    cfg_hosts = configmod.load(hosted).hosts
    assert [(h["name"], h["ssh"], h["service"]) for h in cfg_hosts] == [("pc", "me@192.168.2.15", "x.service")]
    configmod.set_host(hosted, "nas", "me@nas.local")                       # a second one, next to the first
    configmod.set_host(hosted, "pc", "me@10.0.0.5")                         # the same name: changed, not added twice
    hosts = {h["name"]: (h["ssh"], h["service"]) for h in configmod.load(hosted).hosts}
    assert hosts == {"pc": ("me@10.0.0.5", ""), "nas": ("me@nas.local", "")}, hosts
    assert active(open(hosted).read()).count("[host pc]") == 1
    configmod.set_section(hosted, "[host nas]", [])                          # taken out again
    assert [h["name"] for h in configmod.load(hosted).hosts] == ["pc"] and "# the jobs\n[names]" in open(hosted).read()
    before = open(hosted).read()
    try:
        configmod.set_host(hosted, "bad", "-oProxyCommand=x")
        raise AssertionError("an address that is an option to ssh")
    except configmod.ConfigError:
        pass
    assert open(hosted).read() == before

    # the questions for one computer: the address is tried, then the service, then the name
    now_cfg = configured("[deck]\nrepos = a/b\n")
    open(plain, "w").write("[deck]\nrepos = a/b\n")
    w = setupmod.Wizard.for_host(now_cfg, Checks(), path=plain, threaded=False)
    assert w.step == "ssh" and w.mode == "host"
    answer(w, "me@192.168.2.15")
    assert w.step == "service"
    answer(w, "x.service")
    assert w.step == "hostname" and w.field == "pc"                          # an address of numbers is not a name
    answer(w, "has space")
    assert w.step == "hostname" and w.bad
    answer(w, "nas-pc")
    assert w.step == "save" and w.saved and w.answers["host_name"] == "nas-pc"
    assert "Added: nas-pc" in " ".join(map(str, w.text()))
    assert [(h["name"], h["ssh"]) for h in configmod.load(plain).hosts] == [("nas-pc", "me@192.168.2.15")]
    answer(w)
    assert w.finished and w.saved
    for address, name in (("me@nas.local", "nas"), ("me@my-pc", "my-pc"), ("me@10.0.0.9", "pc"), ("me@fe80::1", "pc")):
        w = setupmod.Wizard.for_host(now_cfg, Checks(), path=plain, threaded=False)
        answer(w, address)
        assert w.answers["host_name"] == name, (address, w.answers["host_name"])
    w = setupmod.Wizard.for_host(now_cfg, Checks(ssh=False), path=plain, threaded=False)    # ssh says no: said once, then kept
    answer(w, "me@pc")
    assert w.step == "ssh" and "refuses the connection" in w.note
    answer(w)
    assert w.step == "service"
    w = setupmod.Wizard.for_host(now_cfg, Checks(), path=plain, threaded=False)
    w.feed(27)
    assert w.finished and w.cancelled and not w.saved

    # the repositories: added to and taken from; a name gh cannot see is refused; one that the runners need stays
    repo_file = os.path.join(tmp, "repos.ini")
    open(repo_file, "w").write("# mine\n[deck]\nrepos = a/b\n\n[local]\nname = box\ndir = ~/x\ncount = 1\nrepo = a/b\n")
    now_cfg = configmod.load(repo_file)
    w = setupmod.Wizard.for_repos(now_cfg, Checks(seen={"x/y": False}), path=repo_file, threaded=False)
    assert w.step == "repos" and w.mode == "repos" and w.field == "a/b"          # what is watched is there to edit
    answer(w, "a/b, x/y")
    assert w.step == "repos" and w.bad and "cannot see x/y" in w.note
    answer(w, "")
    assert w.step == "repos" and w.bad
    answer(w, "a/b, c/d")
    assert w.step == "save" and w.saved and "Watching: a/b, c/d" in " ".join(map(str, w.text()))
    assert configmod.load(repo_file).repos == ["a/b", "c/d"] and "# mine" in open(repo_file).read()
    assert "[local]\nname = box" in open(repo_file).read()                        # the rest as it was
    w = setupmod.Wizard.for_repos(configmod.load(repo_file), Checks(), path=repo_file, threaded=False)
    kept = open(repo_file).read()
    answer(w, "c/d")                                                              # the runners' repository a/b would be gone
    assert w.step == "save" and not w.saved and "not in [deck] repos" in w.note and w.bad
    assert open(repo_file).read() == kept                                         # the file is as it was

    # the menu: a list on the screen, chosen with the arrows and Enter, or with a number
    class Keys:
        def __init__(self, keys):
            self.keys = list(keys)

        def size(self):
            return 30, 100

        def key(self, wait=1.0):
            return self.keys.pop(0) if self.keys else 27

    real_flush = terminal.Screen.flush
    terminal.Screen.flush = lambda self: None
    try:
        things = ["add", "repos", "workflows"]
        assert setupmod.menu(Keys([13]), "Settings", things) == 0
        assert setupmod.menu(Keys([terminal.K_DOWN, 13]), "Settings", things) == 1
        assert setupmod.menu(Keys([terminal.K_DOWN] * 9 + [13]), "Settings", things) == 2          # stops at the last
        assert setupmod.menu(Keys([terminal.K_DOWN, terminal.K_UP, terminal.K_UP, 13]), "Settings", things) == 0
        assert setupmod.menu(Keys([ord("3")]), "Settings", things) == 2 and setupmod.menu(Keys([ord("9")] + [27]), "Settings", things) is None
        assert setupmod.menu(Keys([27]), "Settings", things) is None and setupmod.menu(Keys([ord("q")]), "Settings", things) is None
    finally:
        terminal.Screen.flush = real_flush

    # runners that are set up already are found, and offered as the answers
    with tempfile.TemporaryDirectory() as home:
        def registered(folder, name, repo, bom=True):
            os.makedirs(os.path.join(home, folder), exist_ok=True)
            with open(os.path.join(home, folder, ".runner"), "w", encoding="utf-8-sig" if bom else "utf-8") as file:
                file.write('{"agentId": 1, "agentName": "%s", "gitHubUrl": "https://github.com/%s", "workFolder": "_work"}' % (name, repo))
        registered("actions-runner", "mac", "o/app")
        registered("actions-runner-2", "mac-2", "o/app", bom=False)
        registered("actions-runner-3", "mac-3", "o/app")
        registered(".local/share/other-runner", "pc-runner", "o/lib")
        registered("Documents/old/runner", "never", "o/app")                 # macOS asks leave to look: not entered
        os.makedirs(os.path.join(home, "broken"))
        open(os.path.join(home, "broken", ".runner"), "w").write("not json")  # said nothing of, not a crash
        found = runners.find_runners(home)
        assert sorted(item["name"] for item in found) == ["mac", "mac-2", "mac-3", "pc-runner"], found
        assert {item["repo"] for item in found} == {"o/app", "o/lib"}
        before = os.environ.get("HOME")
        os.environ["HOME"] = home
        try:
            plan, left = runners.plan_of(found)
            assert plan == {"name": "mac", "dir": "~/actions-runner", "count": 3, "repo": "o/app"}, plan
            assert [item["name"] for item in left] == ["pc-runner"]
            assert runners.plan_of([]) == (None, [])
            # a row that skips a number is not a row: only the part before the gap
            gap = [item for item in found if item["name"] != "mac-2"]
            assert runners.plan_of(gap)[0]["count"] == 1
            w = setupmod.Wizard(Checks(), threaded=False, finder=lambda: runners.find_runners(home), path=os.path.join(home, "c.ini"))
            assert any("found 4" in str(line) for line in w.text()) and any("pc-runner" in str(line) for line in w.text())
            answer(w)
            assert w.field == "o/app, o/lib"                                   # the repositories of what was found, the managed row's first
            answer(w)
            assert w.step == "count" and w.field == "3"
            answer(w)
            assert w.step == "name" and w.field == "mac"
            answer(w)
            assert w.step == "dir" and w.field == "~/actions-runner"
            answer(w)
            assert w.step == "local_repo" and w.field == "o/app"
            assert w.missing_runners() == []                                   # all three are there: no token is asked
            answer(w)
            assert w.step == "other", w.step
            w.feed(27); w.feed(27); w.feed(27); w.feed(27)                     # back to the number of runners
            assert w.step == "count"
            answer(w, "4")                                                     # a fourth is missing: now a token is asked
            answer(w); answer(w); answer(w)
            assert w.step == "token" and w.missing_runners() == [4]
        finally:
            os.environ["HOME"] = before if before is not None else ""
            if before is None:
                del os.environ["HOME"]

    # a runner that is set up already is not downloaded or registered again
    with tempfile.TemporaryDirectory() as there:
        calls = []
        real_setup, real_start = runners.set_up, runners.Runner.start
        runners.set_up = lambda cfg, runner, token, quiet=False: calls.append(("set_up", runner.name))
        runners.Runner.start = lambda self: calls.append(("start", self.name))
        setupmod.set_up, setupmod.Runner = runners.set_up, runners.Runner
        os.makedirs(os.path.join(there, "r"))
        open(os.path.join(there, "r", ".runner"), "w").close()          # box: set up already
        local = configured("[deck]\nrepos = a/b\n[local]\nname = box\ndir = %s\ncount = 2\n" % os.path.join(there, "r"))
        setupmod.make_runner(local, 1, "TOKEN12345")
        setupmod.make_runner(local, 2, "TOKEN12345")
        assert calls == [("start", "box"), ("set_up", "box-2"), ("start", "box-2")], calls
        runners.set_up, runners.Runner.start = real_setup, real_start
        setupmod.set_up = real_setup

    # the shortest way: one repository, nothing else; and the old file is kept
    made.clear()
    w = wizard_for()
    answer(w); answer(w, "a/b"); answer(w, "0"); w.feed(ord("n")); w.feed(ord("n")); w.feed(ord("n"))
    assert w.step == "review"
    answer(w)
    assert w.step == "done" and made == [] and active(open(path).read()) == "[deck]\nrepos = a/b\n"
    assert open(path + ".bak").read() == written
    answer(w)
    assert w.finished

    # wrong answers are said and kept; escape goes back with the answer still there
    w = wizard_for(seen={"x/y": False})
    answer(w)
    for bad, word in (("", "at least one"), ("xyz", "owner/name"), ("--repo=a/b", "owner/name"), ("x/y", "cannot see")):
        answer(w, bad)
        assert w.step == "repos" and w.bad and word in w.note, (bad, w.note)
    answer(w, "a/b")
    assert w.step == "count"
    for bad in ("x", "10", "-1", "1 "):
        if bad.strip() == "1":
            continue
        answer(w, bad)
        assert w.step == "count" and w.bad, bad
    answer(w, "1")
    answer(w, "has space")
    assert w.step == "name" and w.bad
    w.feed(27)                                  # back to the count
    assert w.step == "count" and w.field == "1"
    w.feed(27); w.feed(27)                      # back to the welcome
    assert w.step == "welcome"
    w.feed(27)
    assert w.finished and w.cancelled           # escape at the start stops it, and nothing was written for it
    assert active(open(path).read()) == "[deck]\nrepos = a/b\n"

    # a warning is said once; the same answer again keeps it
    w = wizard_for(ssh=False)
    answer(w); answer(w, "a/b"); answer(w, "0"); w.feed(ord("y")); answer(w, "me@pc")
    assert w.step == "ssh" and not w.bad and "refuses the connection" in w.note and "Press Enter again" in w.note
    answer(w)
    assert w.step == "service"
    w = wizard_for(gh=(False, False), seen={"a/b": None})
    assert w.gh == (False, False) and any("not installed" in str(line) for line in w.text())
    answer(w); answer(w, "a/b")
    assert w.step == "repos" and "not checked" in w.note
    answer(w)
    assert w.step == "count"

    # slow things wait off the screen's thread, with a spinner; escape stops the waiting
    class Slow(Checks):
        def ssh(self, host):
            time.sleep(0.4)
            return False, "The PC refuses the connection."

        def gh(self):
            time.sleep(0.2)
            return True, True

    def settle(wizard, limit=5):
        end = time.time() + limit
        while wizard.busy and time.time() < end:
            wizard.tick()
            time.sleep(0.02)
        assert not wizard.busy

    w = setupmod.Wizard(Slow(), path=path, threaded=True)
    assert w.busy and "Looking at this computer" in w.view()["busy"] and w.view()["lines"] == [] and w.view()["field"] is None
    w.feed(13)                                   # keys wait while it works
    assert w.step == "welcome" and w.busy
    settle(w)
    assert w.view()["busy"] is None and w.view()["lines"]
    answer(w); settle(w)                         # to the repository question; gh knows the name at once
    answer(w, "a/b"); settle(w)
    answer(w, "0"); w.feed(ord("y"))
    assert w.step == "ssh"
    wipe_and_type(w, "me@pc")
    w.feed(13)
    assert w.busy and "Trying to connect" in w.view()["busy"] and w.view()["field"] == "me@pc" and w.view()["hint"] == "esc: stop waiting"
    w.feed(ord("x"))                              # typing waits too
    assert w.field == "me@pc"
    settle(w)
    assert w.step == "ssh" and "refuses the connection" in w.note and not w.bad
    w.feed(13)                                    # the same again: it goes on at once, with the address kept
    assert not w.busy and w.step == "service" and w.answers["ssh"] == "me@pc"
    w.feed(27)
    w.feed(13)
    assert w.busy
    w.feed(27)                                    # stop waiting: the answer, when it comes, is not used
    assert not w.busy and w.step == "ssh" and w.note == ""
    time.sleep(0.7)
    w.tick()
    assert w.step == "ssh" and w.note == ""

    # ssh's own words, as things to do
    host = "me@pc"
    for said, word in (("ssh: connect to host pc port 22: Connection refused", "SSH server"),
                       ("me@pc: Permission denied (publickey).", "ssh-copy-id me@pc"),
                       ("Host key verification failed.", "ssh me@pc"),
                       ("ssh: Could not resolve hostname pc: Name or service not known", "IP address"),
                       ("ssh: connect to host 10.0.0.9 port 22: Operation timed out", "same network"),
                       ("ssh: connect to host 10.0.0.9 port 22: No route to host", "same network"),
                       ("something else\nlast words", "last words"), ("", "did not connect")):
        assert word in setupmod.explain_ssh(said, host), (said, setupmod.explain_ssh(said, host))

    # a token that is not one is refused; none at all asks gh later
    w = wizard_for()
    answer(w); answer(w, "a/b"); answer(w, "1"); answer(w); answer(w, os.path.join(tmp, "none"))
    assert w.step == "token"
    answer(w, "bad token!")
    assert w.step == "token" and w.bad
    answer(w, "")
    assert w.step == "other"

# --- the first start on a real terminal screen, with keys typed into it
if not system.WINDOWS:
    import pty, select, fcntl, termios, struct
    with tempfile.TemporaryDirectory() as tmp:
        for name, body in (("gh", '#!/bin/sh\ncase "$1 $2" in "auth status") exit 0;; "api repos/owner/name") echo owner/name; exit 0;; esac\nexit 1\n'),):
            with open(os.path.join(tmp, name), "w") as file:
                file.write(body)
            os.chmod(os.path.join(tmp, name), 0o755)
        env = dict(os.environ, PATH=tmp + os.pathsep + os.environ["PATH"], HOME=tmp, SHELL="/bin/bash", TERM="xterm-256color",
                   RUNNERDECK_CONFIG=os.path.join(tmp, "c", "config.ini"), RUNNERDECK_HOME=tmp, PYTHONPATH=ROOT)
        pid, fd = pty.fork()
        if pid == 0:
            os.chdir(tmp)
            os.execvpe(sys.executable, [sys.executable, "-m", "runnerdeck"], env)
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 32, 100, 0, 0))
        seen = ""

        def until(word, seconds=20):
            global seen
            end = time.time() + seconds
            while time.time() < end:
                if word in seen:
                    return
                ready, _, _ = select.select([fd], [], [], 0.2)
                if ready:
                    try:
                        seen += os.read(fd, 65536).decode("utf-8", "replace")
                    except OSError:
                        break
            raise AssertionError(f"never saw {word!r}; the end was: {seen[-400:]!r}")

        def send(text, then):
            global seen
            seen = ""
            os.write(fd, text.encode())
            until(then)

        until("a few questions")                 # the welcome, once it has looked around
        send("\r", "Which repository")
        send("owner/name\r", "How many runners")
        send("0\r", "second computer")
        send("n", "approval")
        send("n", "runnerdeck` command")
        send("y", "This is the config file")
        send("\r", "Setup is done")
        send("\r", "gh did not answer")        # the main screen, saying why there are no runs
        os.write(fd, b"qq")
        _, status = os.waitpid(pid, 0)
        assert os.WEXITSTATUS(status) == 0, status
        assert active(open(os.path.join(tmp, "c", "config.ini")).read()) == "[deck]\nrepos = owner/name\n"
        assert os.path.getsize(os.path.join(tmp, "runnerdeck.pyz")) > 1000
        assert ".local/bin" in open(os.path.join(tmp, ".bashrc")).read() and os.access(os.path.join(tmp, ".local", "bin", "runnerdeck"), os.X_OK)
        # And the program started again finds its config and does not ask.
        out = subprocess.run([sys.executable, "-m", "runnerdeck", "--status"], env=env, cwd=tmp, capture_output=True, text=True, timeout=60)
        assert out.returncode == 0 and "Welcome" not in out.stdout and "◐ runnerdeck" in out.stdout, out.stderr

# --- the command: what the installation wrote is said, and a second time it is not written again
if not system.WINDOWS:
    from runnerdeck import app
    with tempfile.TemporaryDirectory() as home:
        saved = {key: os.environ.get(key) for key in ("HOME", "SHELL")}
        try:
            os.environ["HOME"], os.environ["SHELL"] = home, "/bin/zsh"
            first = app.install()
            shell_file = os.path.join(home, ".zshenv")
            launcher = os.path.join(home, ".local", "bin", "runnerdeck")
            assert os.path.exists(os.path.join(home, "runnerdeck.pyz")) and ".zshenv" in first
            assert "Added to " + shell_file in first and ".local/bin" in first, first
            assert open(shell_file).read().count('export PATH="$HOME/.local/bin') == 1
            assert os.access(launcher, os.X_OK)
            # the command itself works, with no shell file read at all: it is a script, not an alias
            ran = subprocess.run([launcher, "--help"], env=dict(os.environ, HOME=home), capture_output=True, text=True, timeout=60)
            assert ran.returncode == 0 and "runnerdeck" in ran.stdout, (ran.returncode, ran.stderr)
            second = app.install()
            assert "already" in second and "Added to" not in second and open(shell_file).read().count('export PATH="$HOME/.local/bin') == 1
        finally:
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

# --- the key w on the main screen opens the list again, and saves to the config that is there
if not system.WINDOWS:
    import pty, select, fcntl, termios, struct
    with tempfile.TemporaryDirectory() as tmp:
        with open(os.path.join(tmp, "ssh"), "w") as file:
            file.write("#!/bin/sh\nexit 0\n")                # an ssh that connects, and says nothing
        os.chmod(os.path.join(tmp, "ssh"), 0o755)
        with open(os.path.join(tmp, "gh"), "w") as file:
            file.write('#!/bin/sh\ncase "$1 $2" in "api repos/"*) echo ok; exit 0;; "workflow list") echo \'[{"name":"CI"},{"name":"Build"},{"name":"TestFlight"},'
                       '{"name":"Screenshots"}]\'; exit 0;; esac\nexit 1\n')
        os.chmod(os.path.join(tmp, "gh"), 0o755)
        config_file = os.path.join(tmp, "config.ini")
        open(config_file, "w").write("# mine\n[deck]\nrepos = owner/name\n\n[approval]\nworkflows = TestFlight\nlabel = testflight-request\n")
        env = dict(os.environ, PATH=tmp + os.pathsep + os.environ["PATH"], HOME=tmp, TERM="xterm-256color",
                   RUNNERDECK_CONFIG=config_file, RUNNERDECK_HOME=tmp, PYTHONPATH=ROOT)
        pid, fd = pty.fork()
        if pid == 0:
            os.chdir(tmp)
            os.execvpe(sys.executable, [sys.executable, "-m", "runnerdeck"], env)
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 32, 110, 0, 0))
        seen = ""

        def pump(seconds):
            global seen
            end = time.time() + seconds
            while time.time() < end:
                ready, _, _ = select.select([fd], [], [], 0.1)
                if ready:
                    try:
                        seen += os.read(fd, 65536).decode("utf-8", "replace")
                    except OSError:
                        return

        def until(word, seconds=20):
            end = time.time() + seconds
            while time.time() < end:
                if word in seen:
                    return
                pump(0.2)
            raise AssertionError(f"never saw {word!r}; the end was: {seen[-300:]!r}")

        def send(text, then):
            global seen
            seen = ""
            os.write(fd, text.encode())
            until(then)

        until("settings")                                  # the footer has the key for the menu
        send("w", "Which workflows must wait")
        assert "[x] TestFlight" in seen and "[ ] CI" in seen   # what is set is chosen to begin with
        seen = ""
        os.write(fd, b" ")                                 # CI on
        pump(1.0)
        send("\r", "Which label")
        send("\r", "Saved.")
        send("\r", "no runs")                              # back on the main screen
        send("m", "Settings")                              # the menu: everything that can be changed
        assert "Add a runner on this machine" in seen and "Remove a computer" in seen and "Where is the config file" in seen
        send("\x1b", "no runs")                            # esc closes it
        send("m", "Settings")
        send("2", "Which repositories do you watch")       # a number chooses: the repositories, as they are now
        send("owner/name, o/other\r", "Saved.")
        send("\r", "no runs")
        send("h", "SSH address")
        send("me@192.168.2.15\r", "runner service")        # tried at once, then it asks for the service
        send("\r", "What do you call this computer")
        send("\r", "Saved.")
        send("\r", "no runs")                              # back on the main screen, with the computer added
        send("\x1b", "Leave runnerdeck")                   # esc asks first: it is easy to press by mistake
        send("n", "no runs")                               # stay: the screen is back
        send("q", "Leave runnerdeck")                      # q is the same key as esc here: it asks too
        send("\x1b", "no runs")                            # esc in the question stays
        send("\x1b", "Leave runnerdeck")
        os.write(fd, b"y")                                 # leave
        _, status = os.waitpid(pid, 0)
        assert os.WEXITSTATUS(status) == 0
        assert open(config_file).read() == ("# mine\n[deck]\nrepos = owner/name, o/other\n\n[approval]\nworkflows = CI, TestFlight\n"
                                            "label = testflight-request\n\n[host pc]\nssh = me@192.168.2.15\n"), open(config_file).read()

# --- the footer keeps the keys of the screen while something is chosen; a computer that did not answer has no
# --- box; with two repositories every run and request says which one it is of
import types


def footer_text(width, picking):
    grid = terminal.Grid(1, width)
    boxes.footer(grid, 0, width, "", picking)
    return grid.text()


for picking in ("run", "request", None):
    wide = footer_text(190, picking)
    for key in ("q quit", "m settings", "s start", "x stop", "←→ logs"):
        assert key in wide, (picking, key, wide)
    for key in ("n new runner", "w approval", "h add computer"):             # these are in the settings, not on the line
        assert key not in wide, (picking, key, wide)
assert "runners stay on" in footer_text(190, None)
assert "c cancel" in footer_text(190, "run") and "r run again" in footer_text(190, "run")        # what the chosen run can do
assert "enter start" in footer_text(190, "request") and "d decline" in footer_text(190, "request")
mid = footer_text(110, "run")                                                                  # a normal window: nothing needed is gone
for key in ("↑↓ choose", "c cancel", "r run again", "esc back", "q quit", "m settings", "s start"):
    assert key in mid, (key, mid)
for picking in ("run", "request", None):
    for width in (60, 45):                                                                     # a short one keeps move, back and quit
        small = footer_text(width, picking)
        assert "↑↓" in small and "q quit" in small and len(small) <= width, (picking, width, small)
    assert "esc back" in footer_text(45, picking) or picking is None
assert "y yes" in footer_text(100, "dialog") and "q quit" not in footer_text(100, "dialog")    # a question has only its own keys

two = configured("[deck]\nrepos = o/alpha, o/beta\n")
one = configured("[deck]\nrepos = o/alpha\n")


def drawn(cfg_used, queue, pcs=(), width=110):
    grid = terminal.Grid(30, width)
    boxes.paint(grid, cfg_used, [], queue, None, 0, "", pcs=list(pcs))
    return grid.text()


nothing = types.SimpleNamespace(runs=[], requests=[], problem="", jobs={}, working={}, said="")
stub = dict(name="pc", host="me@pc", service="x", now={}, cpu=[], gpu=[], state=lambda: ("listening", "", None, ""))
down = types.SimpleNamespace(failed=True, reachable=lambda: False, **stub)
fresh = types.SimpleNamespace(failed=False, reachable=lambda: False, **stub)
up = types.SimpleNamespace(failed=False, reachable=lambda: True, **dict(stub, now={
    "cpu": 10.0, "gpu": None, "load": 1.0, "threads": 4.0, "memory": (1.0, 8.0), "runner": "active", "log": []}, cpu=[10.0]))
text = drawn(two, nothing, [down])
assert "pc not answering" in text.splitlines()[0] and "╭─ pc" not in text         # no box: a line in the head says which
assert "not answering" not in drawn(two, nothing, [fresh]).splitlines()[0]        # not asked yet: nothing said, no box
assert "╭─ pc" in drawn(two, nothing, [up]) and "not answering" not in drawn(two, nothing, [up])

def a_run(repo, number):
    return {"repo": repo, "databaseId": number, "workflowName": "Build", "headBranch": "main", "headSha": "abcdef1234",
            "status": "completed", "conclusion": "success", "createdAt": "2026-10-30T10:00:00Z"}

asked_one = {"repo": "o/beta", "row": -1000001, "number": 1, "workflow": "Deploy", "branch": "main", "sha": "abcdef1", "note": "Mask lag"}
both = types.SimpleNamespace(runs=[a_run("o/alpha", 1), a_run("o/alpha", 2)], requests=[asked_one], problem="", jobs={},
                             working={}, said="")
text = drawn(two, both)
rows = [line for line in text.splitlines() if "Build" in line]
assert len(rows) == 2 and all("alpha" in line for line in rows), rows       # all the runs shown are of alpha, and it says so
assert any("Deploy" in line and "beta" in line and "Mask lag" in line for line in text.splitlines()), text
rows = [line for line in drawn(one, both).splitlines() if "Build" in line]
assert len(rows) == 2 and not any("alpha" in line for line in rows), rows         # one repository: nothing to tell apart
assert boxes.repo_labels(["a/app", "b/lib"]) == {"a/app": "app", "b/lib": "lib"}
assert boxes.repo_labels(["a/app", "b/app", "c/lib"]) == {"a/app": "a/app", "b/app": "b/app", "c/lib": "lib"}

# --- builds that are not on GitHub: run as they are, recorded, read, and drawn
import json
import threading

with tempfile.TemporaryDirectory() as data:
    env = dict(os.environ, RUNNERDECK_DATA=data)
    # the command runs as it is: its output goes through and its exit code is ours
    out = subprocess.run([sys.executable, "-m", "runnerdeck", "run", "--name", "a test", "--", sys.executable, "-c",
                          "print('hello'); raise SystemExit(3)"], env=env, cwd=ROOT, capture_output=True, text=True)
    assert out.returncode == 3 and out.stdout == "hello\n", out
    found = builds.recent(root=data)
    assert len(found) == 1 and found[0]["name"] == "a test" and found[0]["status"] == "failure" and found[0]["code"] == 3
    assert found[0]["end"] >= found[0]["start"] and found[0]["host"] and "raise SystemExit(3)" in found[0]["cmd"]
    assert builds.record([sys.executable, "-c", "pass"], root=data) == 0
    assert builds.record(["no-such-command-xyz-123"], root=data) == 127
    by_status = [item["status"] for item in builds.recent(root=data)]
    assert sorted(by_status) == ["failure", "failure", "success"], by_status
    assert builds.default_name(["cargo", "test", "--workspace"]) == "cargo test"
    assert builds.default_name(["dev/check.sh"]) == "check.sh" and builds.default_name(["make", "-j8"]) == "make"
    assert builds.default_name(["python3", "some/long/path.py"]) == "python3"
    assert subprocess.run([sys.executable, "-m", "runnerdeck", "run"], env=env, cwd=ROOT, capture_output=True).returncode == 2

    # a build that is still running, one that was interrupted, and one that was stopped
    now_t = time.time()
    path = os.path.join(builds.folder(data), "live.json")
    builds.write(path, {"id": "live", "name": "live", "start": now_t - 5, "end": None, "code": None})
    assert [i["status"] for i in builds.recent(root=data) if i["name"] == "live"] == ["running"]
    os.utime(path, (now_t - 600, now_t - 600))                                     # nobody touched it for ten minutes
    assert [i["status"] for i in builds.recent(root=data) if i["name"] == "live"] == ["interrupted"]
    builds.write(path, {"id": "live", "name": "live", "start": now_t - 5, "end": now_t, "code": 130})
    assert [i["status"] for i in builds.recent(root=data) if i["name"] == "live"] == ["cancelled"]
    os.remove(path)

    # a build that runs is touched, so that it stays running; a record that is not one is not shown
    first = []

    def long_build():
        first.append(builds.record([sys.executable, "-c", "import time; time.sleep(1.2)"], name="slow", root=data, beat=0.1))
    runner_thread = threading.Thread(target=long_build)
    runner_thread.start()
    time.sleep(0.4)
    slow = [f for f in os.listdir(builds.folder(data)) if f.endswith(".json") and "slow" in open(os.path.join(builds.folder(data), f)).read()]
    stamp_early = os.stat(os.path.join(builds.folder(data), slow[0])).st_mtime
    time.sleep(0.5)
    assert os.stat(os.path.join(builds.folder(data), slow[0])).st_mtime > stamp_early
    assert [i["status"] for i in builds.recent(root=data) if i["name"] == "slow"] == ["running"]
    runner_thread.join()
    assert [i["status"] for i in builds.recent(root=data) if i["name"] == "slow"] == ["success"] and first == [0]
    open(os.path.join(builds.folder(data), "junk.json"), "w").write("not json")
    open(os.path.join(builds.folder(data), "other.json"), "w").write(json.dumps({"name": 5}))
    assert all(item["name"] != "junk" for item in builds.recent(root=data))
    assert builds.normalize("x", 0, 0) is None and builds.normalize({"name": 5}, 0, 0) is None
    assert builds.normalize({"name": "x\x1b[2J", "start": "soon", "code": True}, 0, 0)["name"] == "x[2J"   # nothing that moves the cursor
    # only the latest are kept
    for number in range(builds.KEEP + 9):
        builds.write(os.path.join(builds.folder(data), f"old-{number:03}.json"), {"id": str(number), "name": "old", "start": 1.0, "end": 2.0, "code": 0})
        os.utime(os.path.join(builds.folder(data), f"old-{number:03}.json"), (1000 + number, 1000 + number))
    builds.prune(builds.folder(data))
    assert len([f for f in os.listdir(builds.folder(data)) if f.endswith(".json")]) == builds.KEEP

# a computer over ssh tells of its builds, as that computer's clock sees them
said_builds = ("now 5000\nbuild 4990 " + json.dumps({"id": "a", "name": "tests", "start": 4000.0, "end": None, "code": None, "branch": "main", "sha": "abc"})
               + "\nbuild 3000 " + json.dumps({"id": "b", "name": "check", "start": 2900.0, "end": 3000.0, "code": 0})
               + "\nbuild 2000 not json\nbuild x {}\nlog\n")
got = machines.parse_pc(said_builds)["builds"]
assert [(b["name"], b["status"]) for b in got] == [("tests", "running"), ("check", "success")], got
assert machines.parse_pc("")["builds"] == []
if sys.platform.startswith("linux"):                                          # the real script, reading real files
    with tempfile.TemporaryDirectory() as data:
        builds.record([sys.executable, "-c", "pass"], name="seen by the script", root=data)
        saved = os.environ.get("RUNNERDECK_DATA")
        os.environ["RUNNERDECK_DATA"] = data
        try:
            mine = machines.ask_pc(None, "")
        finally:
            os.environ["RUNNERDECK_DATA"] = saved
        assert [(b["name"], b["status"]) for b in mine["builds"]] == [("seen by the script", "success")], mine["builds"]

# the box, and where it is on the screen
import types as _types
t0 = time.time()


def a_build(name, status, start, end=None, code=None):
    return {"id": name, "name": name, "status": status, "start": start, "end": end, "code": code, "branch": "main", "sha": "abcdef1",
            "cmd": "", "cwd": "", "host": "pc"}


sample = [a_build("old", "failure", t0 - 9000, t0 - 8700, 1), a_build("now", "running", t0 - 120), a_build("ok", "success", t0 - 500, t0 - 400, 0),
          a_build("stopped", "cancelled", t0 - 700, t0 - 690, 130)]
grid = terminal.Grid(8, 100)
boxes.builds_box(grid, 0, 100, sample)
lines = grid.text().splitlines()
assert "1 running" in lines[0] and lines[1].lstrip("│ ").startswith("…") and "now" in lines[1] and "running" in lines[1]   # what runs, first
assert any("✓" in line and "ok" in line and "succeeded in" in line for line in lines)
assert any("✗" in line and "old" in line and "failed in" in line for line in lines)
assert any("–" in line and "stopped" in line and "cancelled" in line for line in lines)
grid = terminal.Grid(5, 100)
boxes.builds_box(grid, 0, 100, [sample[0]])
assert "not on GitHub" in grid.text() and "running" not in grid.text().splitlines()[0]
assert boxes.span(40) == "40 s" and boxes.span(600) == "10 min"
# in the screen: this computer's builds, and a computer over ssh with its own box
with tempfile.TemporaryDirectory() as data:
    builds.record([sys.executable, "-c", "pass"], name="built here", root=data)
    saved = os.environ["RUNNERDECK_DATA"]
    os.environ["RUNNERDECK_DATA"] = data
    try:
        pc_with = _types.SimpleNamespace(failed=False, reachable=lambda: True, name="workshop", host="me@w", service="x", cpu=[1.0], gpu=[],
                                         state=lambda: ("listening", "", None, ""),
                                         now={"cpu": 1.0, "gpu": None, "load": 0.5, "threads": 4.0, "memory": (1.0, 8.0), "runner": "active",
                                              "log": [], "builds": [a_build("built there", "success", t0 - 60, t0 - 30, 0)]})
        shown = drawn(two, nothing, [pc_with], width=110)
    finally:
        os.environ["RUNNERDECK_DATA"] = saved
    assert "built here" in shown and "builds · workshop" in shown and "built there" in shown, shown
assert "builds" not in drawn(two, nothing, []).replace("builds ·", "x")           # nothing recorded: no box, nothing said

# --- the logs: every runner a tab on the top edge, the one shown on white, the others grey, a dot where a job runs
class Recorder:
    """A canvas that keeps what is put on it and in which style, to see what is drawn how."""

    def __init__(self, height, width):
        self.height, self.width, self.puts = height, width, []

    def put(self, y, x, text, style=""):
        self.puts.append((y, x, text, style))


def a_runner(name, running=False):
    return _types.SimpleNamespace(name=name, state=lambda: ("running" if running else "listening", "", None, ""),
                                  tail=lambda: [f"{name} says one thing", f"{name} says another"])


crew = [a_runner("mac"), a_runner("mac-2", running=True), a_runner("mac-3")]
for shown_index in (0, 1, 2):
    rec = Recorder(10, 100)
    boxes.log_box(rec, 0, 100, 8, crew, shown_index)
    tabs = [(text.strip(), style) for y, x, text, style in rec.puts if y == 0 and style in ("pop-on", "label") and text.strip() in
            ("mac", "● mac-2", "mac-3")]
    assert [t for t, _ in tabs] == ["mac", "● mac-2", "mac-3"], tabs                       # all of them, side by side, a dot where a job runs
    assert [style for _, style in tabs] == ["pop-on" if i == shown_index else "label" for i in range(3)], (shown_index, tabs)
    lines = [text for y, x, text, style in rec.puts if y > 0 and "says" in text]
    assert all(crew[shown_index].name in line for line in lines), lines                    # the log is of the one shown
    xs = [x for y, x, text, style in rec.puts if y == 0 and text.strip() in ("mac", "● mac-2", "mac-3")]
    assert xs == sorted(xs) and len(set(xs)) == 3
# many runners in a narrow box: the shown one is always there
many = [a_runner(f"runner-{n}") for n in range(1, 13)]
for shown_index in (0, 5, 11):
    rec = Recorder(10, 60)
    boxes.log_box(rec, 0, 60, 8, many, shown_index)
    drawn_tabs = [(text.strip(), style) for y, x, text, style in rec.puts if y == 0 and style in ("pop-on", "label")]
    assert (f"runner-{shown_index + 1}", "pop-on") in drawn_tabs, drawn_tabs
    assert all(x + len(text) <= 60 for y, x, text, style in rec.puts if y == 0), rec.puts
assert boxes.fit_tabs([6, 6, 6, 6], 2, 14) == (1, 2) or boxes.fit_tabs([6, 6, 6, 6], 2, 14)[0] <= 2 <= boxes.fit_tabs([6, 6, 6, 6], 2, 14)[1]
assert boxes.fit_tabs([30, 6], 0, 10) == (0, 0)                                        # one that is too long alone is still shown

# --- a login from another computer brings its terminal and its language along: neither may stop the screen
if not system.WINDOWS:
    import pty, select, fcntl, termios, struct
    with tempfile.TemporaryDirectory() as tmp:
        with open(os.path.join(tmp, "gh"), "w") as file:
            file.write("#!/bin/sh\nexit 1\n")
        os.chmod(os.path.join(tmp, "gh"), 0o755)
        with open(os.path.join(tmp, "c.ini"), "w") as file:
            file.write("[deck]\nrepos = a/b\n")

        def screen_with(settings, tty=True):
            """Starts the program in a terminal with these settings in its environment; what it drew, or what it said."""
            env = dict(os.environ, PATH=tmp + os.pathsep + os.environ["PATH"], HOME=tmp, RUNNERDECK_CONFIG=os.path.join(tmp, "c.ini"),
                       RUNNERDECK_HOME=tmp, PYTHONPATH=ROOT, **settings)
            if not tty:
                got = subprocess.run([sys.executable, "-m", "runnerdeck"], env=env, cwd=tmp, stdin=subprocess.DEVNULL,
                                     capture_output=True, text=True, timeout=30)
                return got.returncode, got.stderr
            pid, fd = pty.fork()
            if pid == 0:
                os.chdir(tmp)
                os.execvpe(sys.executable, [sys.executable, "-m", "runnerdeck"], env)
            fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 30, 100, 0, 0))
            seen, end = "", time.time() + 6
            while time.time() < end and "◐ runnerdeck" not in seen and "Error" not in seen:
                ready, _, _ = select.select([fd], [], [], 0.1)
                if ready:
                    try:
                        seen += os.read(fd, 65536).decode("utf-8", "replace")
                    except OSError:
                        break
            os.write(fd, b"qq")
            try:
                os.kill(pid, 9)
            except OSError:
                pass
            os.waitpid(pid, 0)
            return seen

        for settings in ({"TERM": "xterm-256color", "LANG": "C.UTF-8"}, {"TERM": "no-such-terminal-xyz", "LANG": "C.UTF-8"},
                         {"TERM": "", "LANG": "C.UTF-8"}, {"TERM": "xterm-256color", "LC_ALL": "zz_ZZ.UTF-8"},
                         {"TERM": "no-such-terminal-xyz", "LC_ALL": "zz_ZZ.UTF-8", "LANG": "zz_ZZ.UTF-8"}):
            shown = screen_with(settings)
            assert "◐ runnerdeck" in shown and "Traceback" not in shown, (settings, shown[-300:])
        code, said = screen_with({"TERM": "xterm-256color"}, tty=False)               # ssh without -t: no terminal at all
        assert code != 0 and "needs a terminal" in said and "ssh -t" in said and "Traceback" not in said, (code, said)

# --- one file from the package: it runs, and what it starts again (the watcher) finds itself
with tempfile.TemporaryDirectory() as tmp:
    from runnerdeck import app
    pyz = os.path.join(tmp, "runnerdeck.pyz")
    app.build(pyz)
    assert os.path.getsize(pyz) < 200_000
    ini = os.path.join(tmp, "c.ini")
    watching = os.path.join(tmp, "watch.pid")
    with open(ini, "w") as file:
        file.write("[deck]\nrepos = a/b\n[local]\nname = box\ndir = %s\ncount = 1\n" % os.path.join(tmp, "r"))
    os.makedirs(os.path.join(tmp, "r"))
    env = dict(os.environ, RUNNERDECK_CONFIG=ini, PYTHONPATH=pyz)  # as if run from the file: only the archive to import from
    env.pop("PYTHONHOME", None)
    out = subprocess.run([sys.executable, "-c", "from runnerdeck import system; command, env = system.own_command('x'); "
                          "print(env['PYTHONPATH'].split(system.os.pathsep)[0]); print(command[1:])"],
                         env=env, cwd=tmp, capture_output=True, text=True)
    assert out.returncode == 0 and out.stdout.splitlines()[0] == pyz and out.stdout.splitlines()[1] == "['-m', 'runnerdeck', 'x']", out
    started = subprocess.run([sys.executable, "-c", "from runnerdeck import config, runners; cfg = config.load(); runners.keep_watch(cfg); "
                              "import time; time.sleep(1.5); print(runners.alive(cfg.watch)); runners.end(cfg.watch); "
                              "time.sleep(0.5); print(runners.alive(cfg.watch))"],
                             env=env, cwd=tmp, capture_output=True, text=True, timeout=60)
    lines = started.stdout.split()
    assert started.returncode == 0 and lines[0] != "None" and lines[1] == "None", (started.stdout, started.stderr)

import shutil as _shutil
_shutil.rmtree(os.environ["RUNNERDECK_DATA"], ignore_errors=True)
print("ok")
