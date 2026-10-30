#!/usr/bin/env python3
"""python3 tests/test_runner.py — config, requests, the machine's answer, the screen, one file."""
import configparser
import os
import re
import stat
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from runner import config as configmod, github, machines, runners, system, terminal


def configured(text):
    config = configparser.ConfigParser()
    config.read_string(text)
    return configmod.configure(config)


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
del platform.system, platform.machine  # back to the real ones

# --- the keys are curses' own numbers, so that Windows can say the same
if terminal.curses:
    assert (terminal.K_UP, terminal.K_DOWN, terminal.K_LEFT, terminal.K_RIGHT, terminal.K_ENTER, terminal.K_RESIZE, terminal.K_BACKSPACE) == (
        terminal.curses.KEY_UP, terminal.curses.KEY_DOWN, terminal.curses.KEY_LEFT, terminal.curses.KEY_RIGHT,
        terminal.curses.KEY_ENTER, terminal.curses.KEY_RESIZE, terminal.curses.KEY_BACKSPACE)

# --- it loads where there is no curses, as on Windows
out = subprocess.run([sys.executable, "-c", "import sys; sys.modules['curses'] = None; sys.path.insert(0, %r); "
                      "import runner.app, runner.terminal; assert runner.terminal.curses is None" % ROOT], capture_output=True, text=True)
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
        env = dict(os.environ, PATH=tmp + os.pathsep + os.environ["PATH"], RUNNER_CONFIG=config, RUNNER_HOME=tmp)
        out = subprocess.run([sys.executable, "-m", "runner", "--status"], env=env, cwd=ROOT,
                             capture_output=True, text=True, timeout=60)
        assert out.returncode == 0, out.stderr
        assert "workstation" in out.stdout and "box" in out.stdout and "◐ runner" in out.stdout, out.stdout
        # No config: it says what to do, and does not draw.
        env["RUNNER_CONFIG"] = os.path.join(tmp, "none.ini")
        out = subprocess.run([sys.executable, "-m", "runner", "--status"], env=env, cwd=ROOT, capture_output=True, text=True)
        assert out.returncode != 0 and "--init" in out.stderr, out.stderr
        # --init writes an example that is itself a valid config, and does not overwrite.
        out = subprocess.run([sys.executable, "-m", "runner", "--init"], env=env, cwd=ROOT, capture_output=True, text=True)
        assert out.returncode == 0 and os.path.exists(env["RUNNER_CONFIG"]), out.stderr
        cfg = configured(open(env["RUNNER_CONFIG"]).read())
        assert cfg.repos == ["owner/name"] and cfg.local["count"] == 1


    assert "creationflags" not in system.apart() and system.exists(os.getpid()) and not system.exists(2**22 + 12345)

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

# --- one file from the package: it runs, and what it starts again (the watcher) finds itself
with tempfile.TemporaryDirectory() as tmp:
    from runner import app
    pyz = os.path.join(tmp, "runner.pyz")
    app.build(pyz)
    assert os.path.getsize(pyz) < 200_000
    ini = os.path.join(tmp, "c.ini")
    watching = os.path.join(tmp, "watch.pid")
    with open(ini, "w") as file:
        file.write("[deck]\nrepos = a/b\n[local]\nname = box\ndir = %s\ncount = 1\n" % os.path.join(tmp, "r"))
    os.makedirs(os.path.join(tmp, "r"))
    env = dict(os.environ, RUNNER_CONFIG=ini, PYTHONPATH=pyz)  # as if run from the file: only the archive to import from
    env.pop("PYTHONHOME", None)
    out = subprocess.run([sys.executable, "-c", "from runner import system; command, env = system.own_command('x'); "
                          "print(env['PYTHONPATH'].split(system.os.pathsep)[0]); print(command[1:])"],
                         env=env, cwd=tmp, capture_output=True, text=True)
    assert out.returncode == 0 and out.stdout.splitlines()[0] == pyz and out.stdout.splitlines()[1] == "['-m', 'runner', 'x']", out
    started = subprocess.run([sys.executable, "-c", "from runner import config, runners; cfg = config.load(); runners.keep_watch(cfg); "
                              "import time; time.sleep(1.5); print(runners.alive(cfg.watch)); runners.end(cfg.watch); "
                              "time.sleep(0.5); print(runners.alive(cfg.watch))"],
                             env=env, cwd=tmp, capture_output=True, text=True, timeout=60)
    lines = started.stdout.split()
    assert started.returncode == 0 and lines[0] != "None" and lines[1] == "None", (started.stdout, started.stderr)

print("ok")
