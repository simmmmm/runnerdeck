"""The config file: what is read from it, and what is checked on the way in."""
import configparser
import os
import re
import shutil

SLUG = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
WORD = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]*$")
HOST = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@:-]*$")
FOLDER = re.compile(r"^[A-Za-z0-9_./~-]+$")
# Everything the file can say, as comments: written at the foot of every file the
# program makes, to read with cat or in a file manager. Explanations are on their own
# lines: a # after a value would become a part of the value.
REFERENCE = """\
# ---- All the options. Remove the # in front of a line to use it. ----
#
# [deck]
# The repositories. Runs and requests are read from these. Required.
# repos = owner/name, owner/other
# What this computer is called on the screen, in place of its network name (a Linux PC; up to 12 characters).
# computer = linux
#
# [local]
# The runners on this machine: name, name-2, name-3 in the folders dir, dir-2, dir-3.
# Leave the section out to only watch.
# name = box
# dir = ~/actions-runner
# count = 3
# The repository for new runners. The first in [deck] repos if you leave it out.
# repo = owner/name
# The first runner version to download. Each runner updates itself.
# version = 2.338.2
# macOS: this keychain is unlocked before the runners start.
# keychain = ~/Library/Keychains/login.keychain-db
# Linux: a runner that runs as a systemd user service is shown on the screen, and is not started
# or stopped from here. With only this line (and no count) no runner is started from here.
# service = actions-runner.service
#
# [host pc]
# Another computer, read over ssh with a key (never a password). One section for each.
# A Linux PC: its runner is a systemd user service.
# ssh = user@pc
# service = actions-runner.service
#
# [host mac]
# A Mac: kind = macos. Its runners are read from their folders: name, name-2 in dir, dir-2.
# ssh = user@macbook
# kind = macos
# name = mac
# dir = ~/actions-runner
# count = 3
#
# [approval]
# Workflows that start only after you say yes. An issue with the label and a title
# like "Deploy: main a0d3a70" asks for one. The key w on the screen changes these.
# workflows = Deploy, Ship it
# label = deploy-request
#
# [names]
# Short names for jobs in the notifications.
# build = Build
# check = CI
"""
EXAMPLE = "[deck]\nrepos = owner/name\n\n" + REFERENCE


class ConfigError(Exception):
    pass


class NoConfig(ConfigError):
    """There is no config file yet: the first start."""


class Config:
    """The repositories, where the local runners live, the other machines, and
    the workflows that wait for a person. Made by `configure`, handed to what
    needs it."""

    def __init__(self):
        self.repos = []
        self.computer = ""
        self.home = os.path.expanduser("~")
        self.local = None
        self.hosts = []
        self.approval = {"workflows": [], "label": ""}
        self.asked = None
        self.names = {}
        self.version = "2.338.2"
        self.keychain = ""
        self.awake = self.watch = self.jobs = ""


def default_path():
    """The config file: RUNNERDECK_CONFIG, else ~/.config/runnerdeck/config.ini. The program was
    called runner first: a file or a variable under that name is still found, and used when
    there is none under the new one."""
    chosen = os.environ.get("RUNNERDECK_CONFIG") or os.environ.get("RUNNER_CONFIG")
    if chosen:
        return os.path.expanduser(chosen)
    new, old = (os.path.expanduser(f"~/.config/{name}/config.ini") for name in ("runnerdeck", "runner"))
    return old if os.path.exists(old) and not os.path.exists(new) else new


def configure(config):
    """Reads and checks a ConfigParser. Everything that later reaches `gh`, ssh
    or a file name has to look like what it is here."""
    cfg = Config()

    def listed(text):
        return [word.strip() for word in text.split(",") if word.strip()]

    cfg.repos = listed(config.get("deck", "repos", fallback=""))
    cfg.computer = config.get("deck", "computer", fallback="").strip()
    if cfg.computer and (not WORD.match(cfg.computer) or len(cfg.computer) > 12):
        raise ConfigError(f"[deck] computer is a short name, up to 12 characters: {cfg.computer}")
    if not cfg.repos:
        raise ConfigError("[deck] repos is empty: repos = owner/name")
    for repo in cfg.repos:
        if not SLUG.match(repo):
            raise ConfigError(f"not a repository, owner/name: {repo}")
    cfg.home = os.path.expanduser(os.environ.get("RUNNERDECK_HOME") or os.environ.get("RUNNER_HOME") or "~")
    if config.has_section("local"):
        local = config["local"]
        # A runner that runs as a systemd service (not started from here) is shown, with `service`: then
        # the count of runners that are started from here is 0 unless it says otherwise.
        service = local.get("service", "").strip()
        cfg.local = {"name": local.get("name", "box"), "dir": os.path.expanduser(local.get("dir", "~/actions-runner")),
                     "count": int(local.get("count", "0" if service else "1")), "repo": local.get("repo", cfg.repos[0]),
                     "service": service}
        if service and not HOST.match(service):
            raise ConfigError(f"[local] service = name.service, like actions-runner.service: {service}")
        if not WORD.match(cfg.local["name"]) or " " in cfg.local["name"]:
            raise ConfigError(f"not a runner name: {cfg.local['name']}")
        if cfg.local["repo"] not in cfg.repos:
            raise ConfigError(f"[local] repo {cfg.local['repo']} is not in [deck] repos")
        cfg.version = local.get("version", cfg.version)
        cfg.keychain = os.path.expanduser(local.get("keychain", ""))
    for section in config.sections():
        if section.startswith("host "):
            name, host = section[5:].strip(), config[section].get("ssh", "")
            service = config[section].get("service", "")
            kind = config[section].get("kind", "linux").strip().lower()
            if not WORD.match(name) or not HOST.match(host) or (service and not HOST.match(service)):
                raise ConfigError(f"[{section}]: a name, ssh = user@host, service = name.service")
            if kind not in ("linux", "macos"):
                raise ConfigError(f"[{section}]: kind is linux or macos")
            runners = []
            if kind == "macos":
                # A Mac's runners are read from their folders: name, name-2 in dir, dir-2.
                if service:
                    raise ConfigError(f"[{section}]: service is for Linux. For a Mac use name, dir and count")
                rname, rdir = config[section].get("name", "mac"), config[section].get("dir", "~/actions-runner")
                try:
                    count = int(config[section].get("count", "0"))
                except ValueError:
                    count = -1
                if not WORD.match(rname) or " " in rname or not FOLDER.match(rdir) or not 0 <= count <= 20:
                    raise ConfigError(f"[{section}]: name, dir (like ~/actions-runner) and count (0 to 20)")
                runners = runner_rows(rname, rdir, count)
            cfg.hosts.append({"name": name, "ssh": host, "service": service, "kind": kind, "runners": runners})
    workflows = listed(config.get("approval", "workflows", fallback=""))
    label = config.get("approval", "label", fallback="").strip()
    if workflows and (not label or not WORD.match(label) or not all(WORD.match(name) for name in workflows)):
        raise ConfigError("[approval] workflows = Name, Name and a label = name")
    cfg.approval = {"workflows": workflows, "label": label}
    # "Deploy: <branch> <sha>": nothing from an issue but a workflow's name,
    # a branch's name and a commit reaches `gh`.
    cfg.asked = (re.compile(r"^(%s): ([A-Za-z0-9][A-Za-z0-9._/-]*) ([0-9a-f]{7,40})$"
                            % "|".join(re.escape(name) for name in workflows)) if workflows else None)
    # A job by its workflow's name: the runner's log says only the job's own.
    cfg.names = dict(config["names"]) if config.has_section("names") else {}
    first = os.path.join(cfg.local["dir"] if cfg.local else os.path.join(cfg.home, "actions-runner"), "")
    cfg.awake, cfg.watch, cfg.jobs = (first + name for name in ("caffeinate.pid", "watch.pid", "jobs.log"))
    return cfg


def load(path=None):
    path = path or default_path()
    config = configparser.ConfigParser()
    if not config.read(path):
        raise NoConfig(f"no config at {path}. Start the program in a terminal to set it up, or run: python3 -m runnerdeck --init")
    return configure(config)


def set_section(path, header, body):
    """The section `header` (like "[approval]") of a config file set to the lines of `body`, or
    taken out when `body` is empty. The rest of the file stays as it is, comments too. The old file
    is kept as .bak, and put back if the new one is not a good config."""
    with open(path) as file:
        lines = file.read().split("\n")
    start = next((i for i, line in enumerate(lines) if line.strip().lower() == header.lower()), None)
    if start is None:
        start = end = len(lines)
    else:
        end = next((i for i in range(start + 1, len(lines)) if lines[i].lstrip().startswith("[")), len(lines))
        # The section is its header and its settings. Blank lines and comments after the
        # last setting are not its: they are the next section's, or a note at the foot.
        while end - 1 > start and (not lines[end - 1].strip() or lines[end - 1].lstrip().startswith("#")):
            end -= 1
        # The comment lines right above the header go with the section when it is taken out.
        while not body and start > 0 and lines[start - 1].lstrip().startswith("#"):
            start -= 1
    new = [header, *body] if body else []
    if new and start == end:
        # A section that was not there: after the last setting, before any comments at the foot.
        last = max((i for i, line in enumerate(lines) if line.strip() and not line.lstrip().startswith("#")), default=-1)
        start = end = last + 1
        new = [""] + new
    lines[start:end] = new
    if not new and 0 < start < len(lines) and not lines[start - 1].strip() and not lines[start].strip():
        del lines[start]
    text = "\n".join(lines).rstrip("\n") + "\n"
    shutil.copyfile(path, path + ".bak")
    try:
        with open(path, "w") as file:
            file.write(text)
        load(path)
    except (ConfigError, OSError):
        shutil.copyfile(path + ".bak", path)
        raise


def set_approval(path, workflows, label):
    """The [approval] section set, or taken out when there are no workflows."""
    set_section(path, "[approval]", [f"workflows = {', '.join(workflows)}", f"label = {label}"] if workflows else [])


def runner_rows(name, folder, count):
    """The runners of a row: (name, folder), then (name-2, folder-2) and so on."""
    return [(name if n == 1 else f"{name}-{n}", folder if n == 1 else f"{folder}-{n}") for n in range(1, count + 1)]


def set_host(path, name, ssh, service="", kind="linux", runners=None):
    """The section [host name]: a computer to read over ssh, added, or changed if it is there. A Mac has
    `runners` {name, dir, count}: the folders its runners are read from."""
    body = [f"ssh = {ssh}"]
    if kind == "macos":
        body.append("kind = macos")
        if runners and runners.get("count"):
            body += [f"name = {runners['name']}", f"dir = {runners['dir']}", f"count = {runners['count']}"]
    elif service:
        body.append(f"service = {service}")
    set_section(path, f"[host {name}]", body)
