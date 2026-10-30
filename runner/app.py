"""The screen's loop, and what runs from the command line."""
import locale
import os
import shutil
import sys
import tempfile
import threading
import zipfile
from .util import read
from .system import WINDOWS
from .config import ConfigError, EXAMPLE, NoConfig, default_path, load
from .runners import Runner, add_runner, keep_watch, runner_count, start_all, stop_all, watch
from .github import Queue, act_on_run, approve, close, row_of
from .machines import build_machines
from .terminal import ConsoleTerminal, CursesTerminal, ENTER, Grid, K_BACKSPACE, K_DOWN, K_LEFT, K_RESIZE, K_RIGHT, K_UP, Screen, colours, curses
from .boxes import paint
from .setup import Wizard, run as run_setup


def show(window, cfg, runners, queue, machine, pcs=()):
    colours()
    # By its row, not its place: the list moves as runs come in.
    shown, note, picked, dialog = 0, "", None, None

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
            elif key == ord("y") or (key in ENTER and dialog["focus"]):
                dialog["then"]()
                dialog = None
            elif key in (ord("n"), ord("q"), 27) or key in ENTER:
                dialog = None
            continue
        if key == 27 and picked is not None:
            picked, note = None, ""
            continue
        if key in (ord("q"), 27):
            return
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
        elif key == 9 and runners:
            shown = (shown + 1) % len(runners)
        elif key == ord("s"):
            window.leave()
            start_all(cfg, runners)
            window.back()
            note = ""
        elif key == ord("w"):
            # The workflows that wait for a yes, chosen again, for the config that is there.
            wizard = Wizard.for_approval(cfg)
            run_setup(window, wizard)
            if wizard.saved:
                try:
                    fresh = load()
                    cfg.approval, cfg.asked = fresh.approval, fresh.asked
                    queue.said = "Saved. Waiting for your yes: " + (", ".join(cfg.approval["workflows"]) or "no workflow")
                except (ConfigError, ValueError) as err:
                    queue.said = f"The file is saved, but cannot be read: {err}"
        elif key == ord("n"):
            def make(token):
                def work():
                    queue.said = add_runner(cfg, runners, token)[0]
                threading.Thread(target=work, daemon=True).start()
                queue.said = "Setting up a new runner…"
            if cfg.local:
                dialog = {"title": "New runner", "words": f"Registration token for {cfg.local['repo']}", "field": "", "then": make}
            else:
                note = "Runners here need a [local] section in the config"


def build(target):
    """One file from the package: `python3 runner.pyz` opens it."""
    import zipapp
    package = os.path.dirname(os.path.abspath(__file__))
    with tempfile.TemporaryDirectory() as tmp:
        shutil.copytree(package, os.path.join(tmp, "runner"), ignore=shutil.ignore_patterns("__pycache__"))
        zipapp.create_archive(tmp, target, interpreter="/usr/bin/env python3", main="runner.app:main", compressed=True)


def install():
    """This as ~/runner.pyz (built, if it is run from source), and `runner` in
    the shell's rc to open it. Not in a login file: opening it at every login
    would start the runners with it."""
    target = os.path.expanduser("~/runner.pyz")
    here = os.path.abspath(sys.argv[0])
    if zipfile.is_zipfile(here):
        if here != target:
            shutil.copyfile(here, target)
    else:
        build(target)
    if WINDOWS:
        command = os.path.expanduser("~/runner.cmd")
        with open(command, "w") as file:
            file.write(f'@"{sys.executable}" "%~dp0runner.pyz" %*\r\n')
        return f"{target} and {command} are made.\nPut {os.path.dirname(command)} on your PATH. Then type: runner"
    rc = os.path.expanduser("~/.zshrc" if os.path.basename(os.environ.get("SHELL", "")) == "zsh" else "~/.bashrc")
    if "runner.pyz" not in read(rc):
        with open(rc, "a") as file:
            file.write(f"\n# runner: starts the runners and shows them\nalias runner='{sys.executable} ~/runner.pyz'\n")
    return f"Open a new terminal window. Then type: runner\n(Or run: source {rc})\nThe program is in {target}."


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
        sys.exit("runner: this Python has no curses")
    return curses.wrapper(lambda window: work(CursesTerminal(window)))


def screen(*args):
    terminal(lambda console: show(console, *args))


def first_start():
    """The questions, on the screen. The config they make, or None."""
    wizard = Wizard(install=install)
    return terminal(lambda console: run_setup(console, wizard))


def main(args=None):
    args = sys.argv[1:] if args is None else args
    locale.setlocale(locale.LC_ALL, "")
    if WINDOWS:
        sys.stdout.reconfigure(encoding="utf-8")
    if "--help" in args or "-h" in args:
        print(sys.modules[__package__].__doc__)
        return
    if "--init" in args:
        init()
        return
    if "--build" in args:
        at = args.index("--build") + 1
        build(args[at] if at < len(args) else "runner.pyz")
        return
    cfg, missing = None, None
    if "--setup" not in args:
        try:
            cfg = load()
        except NoConfig as err:
            missing = err
        except (ConfigError, ValueError) as err:
            sys.exit(f"runner: {err}")
    if cfg is None:
        # The first start asks its questions, if there is somebody to ask.
        if "--status" in args or not (sys.stdin.isatty() and sys.stdout.isatty()):
            sys.exit(f"runner: {missing or 'setup needs a terminal'}")
        cfg = first_start()
        if cfg is None:
            sys.exit("runner: setup stopped. Nothing was written.")
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
