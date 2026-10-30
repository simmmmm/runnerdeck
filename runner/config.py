"""The config file: what is read from it, and what is checked on the way in."""
import configparser
import os
import re

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
    return os.path.expanduser(os.environ.get("RUNNER_CONFIG", "~/.config/runner/config.ini"))


def configure(config):
    """Reads and checks a ConfigParser. Everything that later reaches `gh`, ssh
    or a file name has to look like what it is here."""
    cfg = Config()

    def listed(text):
        return [word.strip() for word in text.split(",") if word.strip()]

    cfg.repos = listed(config.get("deck", "repos", fallback=""))
    if not cfg.repos:
        raise ConfigError("[deck] repos is empty: repos = owner/name")
    for repo in cfg.repos:
        if not SLUG.match(repo):
            raise ConfigError(f"not a repository, owner/name: {repo}")
    cfg.home = os.path.expanduser(os.environ.get("RUNNER_HOME", "~"))
    if config.has_section("local"):
        local = config["local"]
        cfg.local = {"name": local.get("name", "box"), "dir": os.path.expanduser(local.get("dir", "~/actions-runner")),
                     "count": int(local.get("count", "1")), "repo": local.get("repo", cfg.repos[0])}
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
            if not WORD.match(name) or not HOST.match(host) or (service and not HOST.match(service)):
                raise ConfigError(f"[{section}]: a name, ssh = user@host, service = name.service")
            cfg.hosts.append({"name": name, "ssh": host, "service": service})
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
        raise NoConfig(f"no config at {path}. Start the program in a terminal to set it up, or run: python3 -m runner --init")
    return configure(config)
