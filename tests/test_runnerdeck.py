#!/usr/bin/env python3
"""python3 tests/test_runnerdeck.py — config, requests, the machine's answer, the screen."""
import configparser
import os
import stat
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import runnerdeck as deck


def configured(text):
    config = configparser.ConfigParser()
    config.read_string(text)
    deck.configure(config)


def refuses(text, word):
    try:
        configured(text)
    except deck.ConfigError as err:
        assert word in str(err), (word, str(err))
        return
    raise AssertionError(f"accepted: {text!r}")


# --- config: what reaches gh, ssh or a file name has to look like what it is
configured("[deck]\nrepos = a/b, c/d\n[approval]\nworkflows = Deploy, Ship it\nlabel = ask\n")
assert deck.REPOS == ["a/b", "c/d"] and deck.LOCAL is None and deck.HOSTS == []
refuses("", "empty")
refuses("[deck]\nrepos = a/b/c\n", "not a repository")
refuses("[deck]\nrepos = --repo=x/y\n", "not a repository")
refuses("[deck]\nrepos = a/b\n[host pc]\nssh = -oProxyCommand=x\n", "ssh = user@host")
refuses("[deck]\nrepos = a/b\n[host pc]\nssh = u@h\nservice = a b\n", "service")
refuses("[deck]\nrepos = a/b\n[local]\nrepo = x/y\n", "not in [deck]")
refuses("[deck]\nrepos = a/b\n[approval]\nworkflows = Deploy\n", "label")
refuses("[deck]\nrepos = a/b\n[approval]\nworkflows = -x\nlabel = ask\n", "label")

# --- requests: a workflow of the list, a branch, a commit; and nothing else
configured("[deck]\nrepos = a/b, c/d\n[approval]\nworkflows = Deploy, Ship it\nlabel = ask\n")
good = deck.asked({"number": 1, "title": "Deploy: feature-x a0d3a70", "body": "Mask lag\nmore"}, "a/b", 0)
assert (good["workflow"], good["branch"], good["sha"], good["note"], good["repo"]) == ("Deploy", "feature-x", "a0d3a70", "Mask lag", "a/b")
assert deck.asked({"number": 1, "title": "Ship it: main a0d3a70"}, "a/b", 0)["workflow"] == "Ship it"
for title in ("Deploy: --repo=other a0d3a70", "Deploy: main", "Deploy: main xyz", "Run Deploy: main a0d3a70",
              "Deploy: a b a0d3a70", "Deploy: main a0d3a70; rm", "Other: main a0d3a70"):
    assert deck.asked({"number": 2, "title": title}, "a/b", 0) is None, title
# The same issue number in two repositories is two rows, and neither is a run's.
one, two = (deck.asked({"number": 7, "title": "Deploy: m a0d3a70"}, repo, index) for index, repo in enumerate(("a/b", "c/d")))
assert one["row"] < 0 and two["row"] < 0 and one["row"] != two["row"]
configured("[deck]\nrepos = a/b\n")
assert deck.asked({"number": 3, "title": "Deploy: main a0d3a70"}) is None  # nothing waits where nothing is gated

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
now = deck.parse_pc(said)
assert round(now["cpu"]) == 67, now["cpu"]
assert now["memory"] == (16.0, 32.0) and now["vram"] == (4.0, 16.0)
assert (now["gpu"], now["gpu_temp"], now["gpu_power"], now["cpu_temp"]) == (37, 58, 142, 71.25)
assert now["log"][-1] == "2026-10-30 18:12:00Z: Running job: check[2J"  # no escape reaches the screen
assert deck.said_by(now["log"])[:2] == ("running", "check[2J")
assert deck.parse_pc("threads x\ngpu_temp \nlog\n")["gpu_temp"] is None
assert deck.parse_pc("")["cpu"] is None and deck.parse_pc("")["memory"] is None
assert deck.ask_pc("-oProxyCommand=x") is None and deck.ask_pc("pc", "a b") is None

# --- the real script, here: it answers on a machine with no GPU, no unit and no ssh
here = deck.ask_pc(None, "")
assert here and here["threads"] and here["memory"] and here["gpu"] is None and here["log"] == []

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
    out = subprocess.run([sys.executable, os.path.join(ROOT, "runnerdeck.py"), "--status"], env=env,
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    assert "workstation" in out.stdout and "box" in out.stdout and "◐ runnerdeck" in out.stdout, out.stdout
    # No config: it says what to do, and does not draw.
    env["RUNNERDECK_CONFIG"] = os.path.join(tmp, "none.ini")
    out = subprocess.run([sys.executable, os.path.join(ROOT, "runnerdeck.py"), "--status"], env=env, capture_output=True, text=True)
    assert out.returncode != 0 and "--init" in out.stderr, out.stderr
    # --init writes an example that is itself a valid config, and does not overwrite.
    out = subprocess.run([sys.executable, os.path.join(ROOT, "runnerdeck.py"), "--init"], env=env, capture_output=True, text=True)
    assert out.returncode == 0 and os.path.exists(env["RUNNERDECK_CONFIG"]), out.stderr
    configured(open(env["RUNNERDECK_CONFIG"]).read())
    assert deck.REPOS == ["owner/name"] and deck.LOCAL["count"] == 1

print("ok")
