"""The screen's loop, and what runs from the command line."""
import locale
import os
import shlex
import shutil
import sys
import tempfile
import threading
import zipfile
from .util import read
from .system import WINDOWS
from .config import ConfigError, EXAMPLE, NoConfig, default_path, load, runner_rows, set_section
from .runners import Runner, add_runner, keep_watch, runner_count, start_all, stop_all, watch
from .github import Queue, act_on_run, approve, close, row_of
from .machines import Pc, RemoteMac, build_machines
from .terminal import ConsoleTerminal, CursesTerminal, ENTER, Grid, K_BACKSPACE, K_DOWN, K_LEFT, K_RESIZE, K_RIGHT, K_UP, Screen, colours, curses
from .boxes import paint
from .builds import run_recorded
from .setup import Wizard, menu, run as run_setup


def show(window, cfg, runners, queue, machine, pcs=()):
    colours()
    # By its row, not its place: the list moves as runs come in.
    shown, note, picked, dialog = 0, "", None, None

    leaving = False

    def leave():
        nonlocal leaving
        leaving = True

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
                close(item, "Declined in runner.")
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

    def approval():
        """The workflows that wait for a yes, chosen again, for the config that is there."""
        wizard = Wizard.for_approval(cfg)
        run_setup(window, wizard)
        if wizard.saved:
            try:
                fresh = load()
                cfg.approval, cfg.asked = fresh.approval, fresh.asked
                queue.said = "Saved. Waiting for your yes: " + (", ".join(cfg.approval["workflows"]) or "no workflow")
            except (ConfigError, ValueError) as err:
                queue.said = f"The file is saved, but cannot be read: {err}"

    def computer():
        """A computer to read over ssh: asked, tried, added to the config and to the screen at once."""
        wizard = Wizard.for_host(cfg)
        run_setup(window, wizard)
        if wizard.saved:
            a = wizard.answers
            name, host, service = a["host_name"], a["ssh"], a["service"]
            new = (RemoteMac(name, host, runner_rows(a["rname"], a["rdir"], a["rcount"])) if a["host_kind"] == "macos"
                   else Pc(name, host, service))
            pcs[:] = [pc for pc in pcs if pc.name != name] + [new]
            try:
                cfg.hosts = load().hosts
            except (ConfigError, ValueError):
                pass
            queue.said = f"{name} is added. It shows as soon as it answers."

    def repositories():
        """The repositories that are watched: added to, or taken from."""
        wizard = Wizard.for_repos(cfg)
        run_setup(window, wizard)
        if wizard.saved:
            try:
                cfg.repos = load().repos
                queue.runs = None
                threading.Thread(target=queue.fetch, daemon=True).start()
                queue.said = "Saved. Watching: " + ", ".join(cfg.repos)
            except (ConfigError, ValueError) as err:
                queue.said = f"The file is saved, but cannot be read: {err}"

    def remove_computer():
        nonlocal dialog, note
        names = [pc.name for pc in pcs if getattr(pc, "host", None)]
        if not names:
            note = "There is no other computer in the config"
            return
        chosen = menu(window, "Remove which computer?", names, intro=("It leaves the config file. The computer itself is not touched.",))
        if chosen is None:
            return
        name = names[chosen]

        def remove():
            try:
                set_section(default_path(), f"[host {name}]", [])
                pcs[:] = [pc for pc in pcs if pc.name != name]
                cfg.hosts = load().hosts
                queue.said = f"{name} is removed"
            except (ConfigError, OSError, ValueError) as err:
                queue.said = f"Not removed: {err}"
        dialog = ask("Remove", f"Remove {name} from the config?", "Remove", "Keep", remove)

    def runner_dialog():
        nonlocal dialog, note
        def make(token):
            def work():
                queue.said = add_runner(cfg, runners, token)[0]
            threading.Thread(target=work, daemon=True).start()
            queue.said = "Setting up a new runner…"
        if cfg.local:
            dialog = {"title": "New runner", "words": f"Registration token for {cfg.local['repo']}", "field": "", "then": make}
        else:
            note = "Runners here need a [local] section in the config"

    def builds_help():
        nonlocal note
        note = "Record a build that is not on GitHub:  runnerdeck run --name tests -- <command>   (docs/builds.md)"

    def config_file():
        nonlocal note
        note = f"Config file: {default_path()}  (read it with cat, or find it in your file manager)"

    def settings():
        """Everything that can be changed, in one list. Each is also on a key of its own."""
        items = (("Add a runner on this machine  (n)", runner_dialog), ("Repositories: add or take out", repositories),
                 ("Workflows that wait for your yes  (w)", approval), ("Add a computer to watch  (h)", computer),
                 ("Remove a computer", remove_computer), ("Where is the config file?", config_file),
                 ("How to record a build that is not on GitHub", builds_help))
        chosen = menu(window, "Settings", [label for label, _ in items])
        if chosen is not None:
            items[chosen][1]()

    while True:
        if queue.said:
            note, queue.said = queue.said, ""
        screen = Screen(window)
        paint(screen, cfg, runners, queue, machine, shown, note, picked, dialog, pcs)
        screen.flush()
        key = window.key()
        if key == -1:
            continue
        if key == K_RESIZE:
            sys.stdout.buffer.write(b"\x1b[2J")
            continue
        if dialog and "field" in dialog:
            if key in ENTER:
                then, value, dialog = dialog["then"], dialog["field"], None
                then(value)
            elif key == 27:
                dialog = None
            elif key in (8, 127, K_BACKSPACE):
                dialog["field"] = dialog["field"][:-1]
            elif 32 <= key < 127:
                dialog["field"] += chr(key)
            continue
        if dialog:
            # Each arrow to its own side: both flipping it, → on the answer
            # already chosen chose the other, and a run was cancelled that
            # was meant to go on.
            if key == K_LEFT:
                dialog["focus"] = True
            elif key == K_RIGHT:
                dialog["focus"] = False
            elif key == 9:
                dialog["focus"] = not dialog["focus"]
            elif key == ord("y") or (key in ENTER and dialog["focus"]) or (key == ord("q") and dialog.get("quit")):
                dialog["then"]()
                dialog = None
                if leaving:
                    return
            elif key in (ord("n"), ord("q"), 27) or key in ENTER:
                dialog = None
            continue
        if key == 27 and picked is not None:
            picked, note = None, ""
            continue
        if key in (ord("q"), 27):
            # q and Esc are the same key here: both ask first. In the question another q says yes.
            dialog = ask("Leave", "Leave runnerdeck? The runners keep running.", "Leave", "Stay", leave)
            dialog["quit"] = True
            continue
        requests, runs = queue.requests, queue.runs or []
        items = [*requests, *runs]
        if key in (K_UP, K_DOWN) and items:
            rows = [row_of(item) for item in items]
            step = 1 if key == K_DOWN else -1
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
                stop_all(cfg, runners)
                note = "Stopped; s starts them again"
            if busy:
                dialog = ask("Stop", f"Stop them? {', '.join(busy)} would fail its job", "Stop", "Keep running", stop)
            else:
                stop()
        elif key in (9, K_RIGHT) and runners:
            shown = (shown + 1) % len(runners)
        elif key == K_LEFT and runners:
            shown = (shown - 1) % len(runners)
        elif key == ord("s"):
            window.leave()
            start_all(cfg, runners)
            window.back()
            note = ""
        elif key == ord("w"):
            approval()
        elif key == ord("h"):
            computer()
        elif key == ord("n"):
            runner_dialog()
        elif key == ord("m"):
            settings()


def build(target):
    """One file from the package: `python3 runnerdeck.pyz` opens it."""
    import zipapp
    package = os.path.dirname(os.path.abspath(__file__))
    with tempfile.TemporaryDirectory() as tmp:
        shutil.copytree(package, os.path.join(tmp, "runnerdeck"), ignore=shutil.ignore_patterns("__pycache__"))
        zipapp.create_archive(tmp, target, interpreter="/usr/bin/env python3", main="runnerdeck.app:main", compressed=True)


def install():
    """This as ~/runnerdeck.pyz (built, if it is run from source), and a command `runnerdeck` that opens
    it: a small script in ~/.local/bin, which a line in the shell's file puts on the PATH. A script and
    not an alias: an alias is only there if the whole of .zshrc runs to its end, and not over ssh without
    a terminal. Nothing is started at a login."""
    target = os.path.expanduser("~/runnerdeck.pyz")
    here = os.path.abspath(sys.argv[0])
    if zipfile.is_zipfile(here):
        if here != target:
            shutil.copyfile(here, target)
    else:
        build(target)
    if WINDOWS:
        command = os.path.expanduser("~/runnerdeck.cmd")
        with open(command, "w") as file:
            file.write(f'@"{sys.executable}" "%~dp0runnerdeck.pyz" %*\r\n')
        return f"{target} and {command} are made.\nPut {os.path.dirname(command)} on your PATH. Then type: runnerdeck"
    launcher = os.path.expanduser("~/.local/bin/runnerdeck")
    os.makedirs(os.path.dirname(launcher), exist_ok=True)
    with open(launcher, "w") as file:
        file.write(f'#!/bin/sh\nexec {shlex.quote(sys.executable)} "$HOME/runnerdeck.pyz" "$@"\n')
    os.chmod(launcher, 0o755)
    # zsh reads .zshenv every time it starts, with a terminal or without; bash, .bashrc; fish reads every
    # file in conf.d (CachyOS and others have fish as the shell: it reads neither of the other two).
    shell = os.path.basename(os.environ.get("SHELL", ""))
    if shell == "fish":
        shell_file = os.path.expanduser("~/.config/fish/conf.d/runnerdeck.fish")
        line = 'fish_add_path -g "$HOME/.local/bin"'
        if os.path.exists(shell_file):
            said = f"{shell_file} is there already."
        else:
            os.makedirs(os.path.dirname(shell_file), exist_ok=True)
            with open(shell_file, "w") as file:
                file.write(f"# runnerdeck: its command is in ~/.local/bin\n{line}\n")
            said = f"Made {shell_file}: {line}"
    else:
        shell_file = os.path.expanduser("~/.zshenv" if shell == "zsh" else "~/.bashrc")
        line = 'export PATH="$HOME/.local/bin:$PATH"'
        if ".local/bin" in read(shell_file):
            said = f"{shell_file} has ~/.local/bin on the PATH already."
        else:
            with open(shell_file, "a") as file:
                file.write(f"\n# runnerdeck: its command is in ~/.local/bin\n{line}\n")
            said = f"Added to {shell_file}: {line}"
    return (f"Open a new terminal window. Then type: runnerdeck\n(Or now: {launcher})\n{said}\n"
            f"The command is {launcher}; the program is in {target}.")


def init():
    path = default_path()
    if os.path.exists(path):
        print(f"{path} is there already; not touched.")
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as file:
        file.write(EXAMPLE)
    print(f"{path} written: edit it, then start the program again.")


def terminal(work):
    """Runs work(terminal) on the screen, and leaves the screen as it was."""
    if WINDOWS:
        with ConsoleTerminal() as console:
            return work(console)
    if curses is None:
        sys.exit("runnerdeck: this Python has no curses")
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        sys.exit("runnerdeck needs a terminal. Over ssh, ask for one: ssh -t host command")
    # The terminal that is named (TERM) may not be known on this system: kitty, alacritty and foot are not
    # on a Mac, and a login from such a PC brings their name along. The screen is drawn with the escape codes
    # that every current terminal knows, so xterm-256color does for all of them.
    try:
        curses.setupterm(os.environ.get("TERM") or "unknown", sys.__stdout__.fileno())
    except curses.error:
        os.environ["TERM"] = "xterm-256color"
    # curses waits a second after an Esc to see whether an arrow key follows: that is the lag.
    # A key sends its whole sequence at once, so a few hundredths are enough.
    os.environ.setdefault("ESCDELAY", "25")
    try:
        return curses.wrapper(lambda window: work(CursesTerminal(window)))
    except curses.error as err:
        sys.exit(f"runnerdeck: the terminal does not work here ({err}; TERM={os.environ.get('TERM', '')}). "
                 "Try: TERM=xterm-256color runnerdeck")


def screen(*args):
    terminal(lambda console: show(console, *args))


def first_start():
    """The questions, on the screen. The config they make, or None."""
    wizard = Wizard(install=install)
    return terminal(lambda console: run_setup(console, wizard))


def main(args=None):
    args = sys.argv[1:] if args is None else args
    try:
        locale.setlocale(locale.LC_ALL, "")
    except locale.Error:
        # The language setting of the computer one logs in from (C.UTF-8, nl_NL ...) may not exist here.
        # Nothing on the screen depends on it: it is drawn as UTF-8 bytes whatever the setting is.
        pass
    if WINDOWS:
        sys.stdout.reconfigure(encoding="utf-8")
    if args[:1] == ["run"]:
        # A command that is run and recorded; no config is needed, and its own exit code is ours.
        sys.exit(run_recorded(args[1:]))
    if "--help" in args or "-h" in args:
        print(sys.modules[__package__].__doc__)
        return
    if "--init" in args:
        init()
        return
    if "--build" in args:
        at = args.index("--build") + 1
        build(args[at] if at < len(args) else "runnerdeck.pyz")
        return
    cfg, missing = None, None
    if "--setup" not in args:
        try:
            cfg = load()
        except NoConfig as err:
            missing = err
        except (ConfigError, ValueError) as err:
            sys.exit(f"runnerdeck: {err}")
    if cfg is None:
        # The first start asks its questions, if there is somebody to ask.
        if "--status" in args or not (sys.stdin.isatty() and sys.stdout.isatty()):
            sys.exit(f"runnerdeck: {missing or 'setup needs a terminal'}")
        cfg = first_start()
        if cfg is None:
            sys.exit("runnerdeck: setup stopped. Nothing was written.")
    runners = [Runner(cfg, n) for n in range(1, runner_count(cfg) + 1)] if cfg.local else []
    if "--install" in args:
        print(install())
        return
    if "--watch" in args:
        watch(cfg, runners)
        return
    if "--status" in args:
        here, pcs = build_machines(cfg, once=True)
        grid = Grid(34 + 5 * len(pcs), 100)
        paint(grid, cfg, runners, Queue(cfg, once=True), here, 0, "", pcs=pcs)
        print(grid.text())
        return
    if any(not runner.running() for runner in runners):
        start_all(cfg, runners)
    # Runners started before there was a watcher get one too.
    if any(runner.running() for runner in runners):
        keep_watch(cfg)
    here, pcs = build_machines(cfg)
    screen(cfg, runners, Queue(cfg), here, pcs)
