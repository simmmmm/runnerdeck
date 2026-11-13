"""The boxes of the screen, and the screen made of them."""
import os
import re
import time
from .util import STAMP, ago, clean, moment
from .builds import recent as recent_builds
from .system import alive
from .github import row_of, run_detail
from .health import ISSUE_ROW, health_box, height_of
from .machines import power, run, watts
from .terminal import GLYPH, MOTION, Inset, Screen, decode, ease, frame, graph, heat, meter, popup, right, spin
from .terminal import progress as progress_of


MARKS = {"running": "●", "listening": "○", "starting": "◌"}


WORDS = {"listening": "Listening", "starting": "Starting…", "stopped": "Stopped", "not set up": "Not set up",
         "unreachable": "Unreachable"}


RESULTS = {"success": "✓", "failure": "✗", "cancelled": "–", "skipped": "–"}


def gauges(canvas, y, half, now, cpu, gpu, tall=1):
    """CPU and GPU as graphs `tall` rows high, memory as a meter, at the left of a machine's
    box; the row under them."""
    row = y
    for name, value, history in (("CPU", now.get("cpu"), cpu), ("GPU", now.get("gpu"), gpu)):
        canvas.put(row, 2, name, "label")
        graph(canvas, row, 7, half - 13, tall, history)
        if value is None:
            canvas.put(row, half - 4, "  —", "dim")
        else:
            canvas.put(row, half - 4, f"{value:3.0f} %", heat(value / 100))
        row += tall
    used = now.get("memory")
    canvas.put(row, 2, "RAM", "label")
    if used:
        meter(canvas, row, 7, half - 22, used[0] / used[1])
        canvas.put(row, half - 13, f"{used[0]:4.1f} / {used[1]:.0f} GB", "plain")
    return row + 1


def mac_box(canvas, y, width, machine, tall=1):
    """CPU and GPU as graphs, memory as a meter; beside them, or under them
    where the screen is narrow, what the battery says and how hot. `tall`: the
    rows of each graph, more where the screen has room."""
    now = machine.now
    wide = width >= 96
    height = (5 if wide else 8) + 2 * (tall - 1)
    # This Mac has the name "mac" and its own load; a Mac over ssh brings its name and what it says of itself.
    title = getattr(machine, "title", "mac")
    summary = machine.summary() if hasattr(machine, "summary") else f"load {os.getloadavg()[0]:.1f} · {os.cpu_count()} cores"
    frame(canvas, y, 0, height, width, title, summary)
    half = (width - 4) // 2 - 1 if wide else width - 4
    row = gauges(canvas, y + 1, half, now, machine.cpu, machine.gpu, tall)
    row = y + 1 if wide else row
    x = half + 4 if wide else 2
    battery = now.get("power") or {}
    canvas.put(row, x, "Power", "label")
    if battery:
        watts = f"{battery['watts']:.0f} W  " if battery.get("watts") is not None else ""
        how = "charging" if battery["charging"] else "on power" if battery["external"] else "on battery"
        canvas.put(row, x + 9, watts, "strong")
        canvas.put(row, x + 9 + len(watts), how, "plain")
    else:
        canvas.put(row, x + 9, "—", "dim")
    row += 1
    canvas.put(row, x, "Battery", "label")
    percent, warm = battery.get("percent"), battery.get("warm")
    if percent is not None:
        # Low is under 20 % away from power.
        low = percent < 20 and not battery["external"]
        meter(canvas, row, x + 9, 12, percent / 100, "bad" if low else "warm" if percent < 40 else "good")
        canvas.put(row, x + 22, f"{percent:3.0f} %", "bad" if low else "plain")
    if warm is not None:
        canvas.put(row, x + 29, f"{warm:.0f} °C", "bad" if warm >= 45 else "plain")
    row += 1
    state = now.get("thermal")
    canvas.put(row, x, "Thermal", "label")
    # How hot, as macOS throttles by it: Serious or worse is too much.
    canvas.put(row, x + 9, state or "—", {"Nominal": "good", "Fair": "warm"}.get(state, "bad" if state else "dim"))
    return y + height


def hot(degrees, warm, bad):
    return "dim" if degrees is None else "bad" if degrees >= bad else "warm" if degrees >= warm else "plain"


def pc_box(canvas, y, width, pc, tall=1):
    """A Linux machine as the Mac above it: CPU and GPU as graphs, memory as a meter;
    beside them, or under them, how hot it is, what the card draws, and its
    runner. A machine that does not answer says so, and shows no old numbers as
    if they were now."""
    now = pc.now if pc.reachable() else {}
    wide = width >= 96
    height = (5 if wide else 8) + 2 * (tall - 1)
    host = pc.host.split("@")[-1] if pc.host else "here"
    if pc.reachable():
        right_side = f"{host} · load {now['load']:.1f} · {now['threads']:.0f} threads" if now.get("load") is not None else host
    else:
        right_side = f"{host} · not answering"
    frame(canvas, y, 0, height, width, pc.name, right_side)
    half = (width - 4) // 2 - 1 if wide else width - 4
    row = gauges(canvas, y + 1, half, now, pc.cpu if pc.reachable() else [], pc.gpu if pc.reachable() else [], tall)
    row = y + 1 if wide else row
    x = half + 4 if wide else 2
    canvas.put(row, x, "Heat", "label")
    # Ryzen's Tctl runs in the 80s under a build and holds to 95; the card's
    # edge sensor is cooler than its junction.
    cpu_temp, gpu_temp = now.get("cpu_temp"), now.get("gpu_temp")
    canvas.put(row, x + 9, f"CPU {cpu_temp:.0f} °C" if cpu_temp is not None else "CPU —", hot(cpu_temp, 80, 90))
    canvas.put(row, x + 21, f"GPU {gpu_temp:.0f} °C" if gpu_temp is not None else "GPU —", hot(gpu_temp, 75, 85))
    row += 1
    canvas.put(row, x, "VRAM", "label")
    vram = now.get("vram")
    canvas.put(row, x + 9, f"{vram[0]:.1f} / {vram[1]:.0f} GB" if vram else "—", "plain" if vram else "dim")
    row += 1
    # The card's power is no use to anyone here. What keeps the processor busy is: a runner's job is in
    # the box below, but a build that was started by hand, or an editor, is only here.
    canvas.put(row, x, "Busy", "label")
    top = now.get("top") or []
    text = "   ".join(f"{name} {share} %" for name, share in top)
    canvas.put(row, x + 9, text[:max(0, width - x - 12)] if text else "nothing much", "plain" if text else "dim")
    return y + height


def progress(job):
    """A busy runner's job: how far, which step, how long still. By the time
    the last good run of the workflow took where there was one — the steps
    are far from even, a Build is mostly app/build.sh — and by the steps
    where there was not."""
    steps = job["steps"]
    done = sum(1 for step in steps if step.get("status") == "completed")
    current = next((step.get("name", "") for step in steps if step.get("status") == "in_progress"), "")
    words = f"step {min(done + 1, len(steps))} of {len(steps)} · {current}" if steps else job["workflow"]
    elapsed = time.time() - job["started"] if job["started"] else None
    if job["typical"] and elapsed is not None:
        left = max(0, round((job["typical"] - elapsed) / 60))
        return min(elapsed / job["typical"], 0.99), words, f"~{left} min left" if left else "about done"
    return (done / len(steps) if steps else 0), words, ""


def repo_labels(repos):
    """The short name of each repository, the part after the owner; the whole
    name where two have the same."""
    shorts = [repo.split("/")[-1] for repo in repos]
    return {repo: short if shorts.count(short) == 1 else repo for repo, short in zip(repos, shorts)}


def put_on(canvas, line, at, width, run, labels, on, style):
    """After the name of the repository: which runner has the run, or what it waits for."""
    if labels:
        name = labels.get(run.get("repo"), run.get("repo", ""))[:20]
        canvas.put(line, at, name, style)
        at += len(name) + 2
    where = on.get(run.get("databaseId"), "")
    if where and at < width - 40:
        canvas.put(line, at, (where if where.startswith("waiting") else f"on {where}")[:max(0, width - at - 34)],
                   "warm" if where.startswith("waiting") else "strong" if style == "dim" else style)


def github_box(canvas, y, width, runs, repos, picked=None, working=None, on=None, age=None):
    working = working or {}
    on = on or {}
    # Every run says which repository it is of as soon as there are two, not only when the
    # runs shown happen to be of both.
    many = len(repos) > 1
    labels = repo_labels(repos)
    # The columns follow the names: "Publish Linux" and "Publish Apple" must not be cut to the same twelve letters.
    name_w = min(24, max([12] + [len(run.get("workflowName", "")) for run in runs]))
    branch_w = min(24, max([8] + [len(run.get("headBranch", "")) for run in runs]))
    branch_at = 4 + name_w + 1
    sha_at = branch_at + branch_w + 1
    repo_at = sha_at + 8
    # How old what is shown is: GitHub is asked every 20 seconds, and a list of minutes ago is not now.
    told = "" if age is None else f" · {span(age)} ago" + (" · stale" if age > 120 else "")
    names = ", ".join(repos) if len(", ".join(repos)) < width - 16 - len(told) else f"{len(repos)} repositories"
    # Red while a workflow's newest finished run failed, not for an old failure that a later run made good.
    newest = {}
    for run in sorted(runs, key=lambda run: run.get("createdAt", ""), reverse=True):
        if run.get("status") == "completed":
            newest.setdefault((run.get("repo"), run.get("workflowName")), run.get("conclusion"))
    failed = any(conclusion in ("failure", "timed_out", "startup_failure") for conclusion in newest.values())
    frame(canvas, y, 0, 2 + len(runs), width, "RUNS", names + told, "bad" if failed else None)
    for line, run in enumerate(runs, start=y + 1):
        doing = working.get(run.get("databaseId"))
        if run.get("databaseId") == picked:
            canvas.put(line, 0, " ▸" + " " * (width - 2), "picked")
            canvas.put(line, 4, run.get("workflowName", "")[:name_w], "picked")
            canvas.put(line, branch_at, run.get("headBranch", "")[:branch_w], "picked")
            canvas.put(line, sha_at, run.get("headSha", "")[:7], "picked")
            put_on(canvas, line, repo_at, width, run, labels if many else None, on, "picked")
            word = f"{doing}…" if doing else run.get("conclusion") or (run.get("status") or "").replace("_", " ")
            right(canvas, line, width, f"{word} · {ago(moment(run.get('createdAt', ''), STAMP))}", "picked")
            continue
        done = run.get("status") == "completed"
        conclusion = run.get("conclusion") or ""
        mark = RESULTS.get(conclusion, "·") if done else spin("…") if run.get("status") == "in_progress" else "·"
        style = {"success": "good", "failure": "bad"}.get(conclusion, "dim") if done else "warm"
        canvas.put(line, 2, mark, style)
        canvas.put(line, 4, run.get("workflowName", "")[:name_w], "strong" if not done else "plain")
        canvas.put(line, branch_at, run.get("headBranch", "")[:branch_w], "dim")
        canvas.put(line, sha_at, run.get("headSha", "")[:7], "dim")
        put_on(canvas, line, repo_at, width, run, labels if many else None, on, "dim")
        word = f"{doing}…" if doing else conclusion if done else (run.get("status") or "").replace("_", " ")
        when = ago(moment(run.get("createdAt", ""), STAMP))
        right(canvas, line, width, f"{word} · {when}", "warm" if doing else style if style != "dim" else "label")
    return y + 2 + len(runs)


BUILD_MARKS = {"running": ("…", "warm"), "success": ("✓", "good"), "failure": ("✗", "bad"),
               "cancelled": ("–", "dim"), "interrupted": ("–", "dim")}


def span(seconds):
    return f"{round(seconds)} s" if seconds < 90 else f"{round(seconds / 60)} min"


def builds_box(canvas, y, width, builds, title="BUILDS"):
    """Builds that did not go through GitHub, as a runner's rows are: what runs now first, then the latest,
    each with how it ended, how long it took and how long ago."""
    shown = sorted(builds, key=lambda b: (b["status"] != "running", -(b["start"] or 0)))[:5]
    busy = sum(1 for b in shown if b["status"] == "running")
    frame(canvas, y, 0, 2 + len(shown), width, title, f"{busy} running" if busy else "not on GitHub")
    for line, build in enumerate(shown, start=y + 1):
        mark, style = BUILD_MARKS[build["status"]]
        running = build["status"] == "running"
        mark = spin(mark) if running else mark
        canvas.put(line, 2, mark, style)
        canvas.put(line, 4, build["name"][:18], "strong" if running else "plain")
        canvas.put(line, 23, build["branch"][:20], "dim")
        canvas.put(line, 44, build["sha"][:7], "dim")
        if running:
            word, when = "running", ago(build["start"])
        else:
            took = f" in {span(build['end'] - build['start'])}" if build["end"] and build["start"] else ""
            word, when = {"success": "succeeded", "failure": "failed"}.get(build["status"], build["status"]) + took, ago(build["end"])
        tail = f"{word} · {when}"
        right(canvas, line, width, tail, style if style != "dim" else "label")
        room = width - 2 - len(tail) - 53
        if build.get("toolchain") and room > 6:
            canvas.put(line, 53, build["toolchain"][:room - 1], "dim")
    return y + 2 + len(shown)


def requests_box(canvas, y, width, requests, picked=None, working=None, labels=None):
    working = working or {}
    frame(canvas, y, 0, 2 + len(requests), width, "WAITING FOR YOU", "a: start · d: decline", "warm")
    # The columns follow the names: "Publish Linux" and "Publish Apple" must not be cut to the same twelve letters.
    plain = [r for r in requests if not r.get("kind")]
    name_w = min(24, max([12] + [len(r["workflow"]) for r in plain]))
    branch_at = 4 + name_w + 1
    sha_at = branch_at + min(24, max([12] + [len(r["branch"]) for r in plain])) + 1
    note_at = sha_at + 8
    for line, request in enumerate(requests, start=y + 1):
        chosen = row_of(request) == picked
        doing = working.get(row_of(request))
        if chosen:
            canvas.put(line, 0, " ▸" + " " * (width - 2), "picked")
        else:
            canvas.put(line, 2, "?", "warm")
        if request.get("kind"):
            # A kind of the config's own: what the issue said, as it is.
            canvas.put(line, 4, request["what"][:44], "picked" if chosen else "strong")
        else:
            canvas.put(line, 4, request["workflow"][:name_w], "picked" if chosen else "strong")
            canvas.put(line, branch_at, request["branch"][:sha_at - branch_at - 1], "picked" if chosen else "dim")
            canvas.put(line, sha_at, request["sha"][:7], "picked" if chosen else "dim")
        words = f"{doing}…" if doing else request["note"]
        at = note_at if not request.get("kind") else 50
        if labels:
            name = labels.get(request["repo"], request["repo"])[:20]
            canvas.put(line, at, name, "picked" if chosen else "dim")
            at += len(name) + 2
        canvas.put(line, at, words[:max(0, width - at - 2)], "picked" if chosen else "warm" if doing else "label")
    return y + 2 + len(requests)


def fit_tabs(sizes, shown, room):
    """Which tabs fit in `room` columns, a space between them: the one shown, and as many of its
    neighbours as there is room for. (first, last)"""
    first = last = shown
    used = sizes[shown]
    grew = True
    while grew:
        grew = False
        if last + 1 < len(sizes) and used + 1 + sizes[last + 1] <= room:
            last += 1
            used += 1 + sizes[last]
            grew = True
        if first > 0 and used + 1 + sizes[first - 1] <= room:
            first -= 1
            used += 1 + sizes[first]
            grew = True
    return first, last


def with_remote(runners, pcs):
    """The runners whose log can be read: those of this machine, then those that are read over ssh or are
    a service. One list, for the tabs of the log and the keys that move between them."""
    more = []
    for pc in pcs:
        if pc.reachable() and hasattr(pc, "runner_list"):
            more += pc.runner_list()
    return list(runners) + more


STAMP_AT = re.compile(r"\[?\d{4}-\d\d-\d\d[ T][\d:.]+Z?\]?:? ")


def log_box(canvas, y, width, height, runners, shown):
    """The log of the runner shown, its newest lines at the foot; a job's start in white, its end in
    the colour of how it ended. All the runners are tabs on the top edge: the one shown on white, the
    others grey, a dot where a job runs."""
    runner = runners[shown]
    right_text = "←→ other log" if width >= 70 else ""
    frame(canvas, y, 0, height, width, "LOG", right_text)
    labels = [f" {spin('●') + ' ' if other.state()[0] == 'running' else ''}{other.name} " for other in runners]
    start = 4 + len("LOG") + 2
    room = width - 2 - start - (len(right_text) + 5 if right_text else 1)
    first, last = fit_tabs([len(label) for label in labels], shown, max(room, len(labels[shown])))
    x = start
    for index in range(first, last + 1):
        canvas.put(y, x, labels[index], "pop-on" if index == shown else "label")
        x += len(labels[index]) + 1
    lines = [line for line in runner.tail() if line.strip()][-(height - 2):] if height > 2 else []
    for at, line in enumerate(lines, start=y + 1):
        style = ("bad" if "Failed" in line else "good" if "Succeeded" in line
                 else "strong" if "Running job" in line else "dim")
        # The time each line starts with, darker than what it says.
        stamp = STAMP_AT.match(line)
        cut = stamp.end() if stamp else 0
        canvas.put(at, 2, line[:min(cut, width - 4)], "frame")
        canvas.put(at, 2 + cut, line[cut:width - 4], style)


def footer(canvas, y, width, note, picking=None, page=1):
    if note:
        canvas.put(y, 1, note[:width - 2], "warm")
        return
    # The keys of the screen are always there, also while a run or a request is chosen: the
    # ones of what is chosen come first. What can be changed is in the settings (m), so n, w and
    # h are not listed: they still work, and the menu names them. Where the width is short, the
    # first three here stay (move, back, quit) and the others go from the right.
    leave = "quit, runners stay on" if width >= 100 else "quit"
    general = (("m", "settings"), ("s", "start"), ("x", "stop"), ("1-4", "pages"), ("q", leave))
    keys = {"run": (("↑↓", "choose"), ("c", "cancel"), ("r", "run again"), ("l", "log"), ("o", "open"), ("esc", "back")) + general,
            "issue": (("↑↓", "choose"), ("o", "open"), ("esc", "back")) + general,
            "request": (("↑↓", "choose"), ("enter", "start"), ("d", "decline"), ("esc", "back")) + general,
            "dialog": (("y", "yes"), ("n", "no"), ("↑↓", "choose"), ("enter", "answer")),
            "field": (("enter", "set up"), ("esc", "cancel")),
            None: ((("↑↓", "choose"),) if page in (1, 2) else (("←→", "other log"),) if page == 3 else ()) + general}[picking]
    must = {"↑↓", "←→", "esc", "q"} if picking in ("run", "request", "issue", None) else {key for key, _ in keys}
    used = sum(len(k) + len(w) + 4 for k, w in keys if k in must)
    shown = []
    for key, words in keys:
        cost = len(key) + len(words) + 4
        if key in must:
            shown.append((key, words))
        elif used + cost <= width - 2:
            used += cost
            shown.append((key, words))
    x = 1
    for key, words in shown:
        canvas.put(y, x, key, "key")
        canvas.put(y, x + len(key) + 1, words, "label")
        x += len(key) + len(words) + 4


def head_why(why):
    """The one thing to do, short enough for the head line; the full words stay in --status."""
    fix = re.search(r"ssh-copy-id \S+", why)
    if fix:
        return "key refused, run: " + fix.group(0)
    return why.split(". ")[0]


# The pages, each for one question. DECK: does anything need me, what runs, what happened. RUNS: what
# happened, and why, step by step. LOGS: what a runner says. MACHINES: how the computers do. 1-4 choose.
PAGES = ((1, "DECK", "DECK_OVERVIEW"), (2, "RUNS", "RUN_MANIFEST"), (3, "LOGS", "RUNNER_LOGS"), (4, "MACHINES", "MACHINES"))
FAILED = ("failure", "timed_out", "startup_failure")
DIGITS = {"0": ("┏━┓", "┃ ┃", "┗━┛"), "1": (" ┓ ", " ┃ ", " ┻ "), "2": ("┏━┓", "┏━┛", "┗━━"), "3": ("━━┓", " ━┫", "━━┛"),
          "4": ("╻ ╻", "┗━┫", "  ╹"), "5": ("┏━━", "┗━┓", "━━┛"), "6": ("┏━━", "┣━┓", "┗━┛"), "7": ("━━┓", "  ┃", "  ╹"),
          "8": ("┏━┓", "┣━┫", "┗━┛"), "9": ("┏━┓", "┗━┫", "━━┛"), "/": ("  ╱", " ╱ ", "╱  ")}
NAME_CHIP = "RUNNERDECK"


def big(canvas, y, x, text, style):
    """A number three rows high, of heavy lines; one row where the font has none."""
    if not GLYPH["digits"]:
        canvas.put(y + 1, x, text, style)
        return
    for row in range(3):
        canvas.put(y + row, x, "".join(DIGITS.get(c, ("   ",) * 3)[row] for c in text), style)


def band(canvas, y, x, width, chip, columns=(), right_text="", tone=None):
    """A table's head: a grey band, its name as a chip, the names of its columns in it."""
    canvas.put(y, x, " " * width, "band")
    canvas.put(y, x + 1, f" {chip} ", f"title-{tone}" if tone else "title")
    for at, label in columns:
        canvas.put(y, x + at, label, "band")
    if right_text:
        canvas.put(y, x + width - 1 - len(right_text), right_text, "band")


def every_runner(cfg, runners, machine, pcs):
    """Each runner with the name of its computer: this one's first, then those read over ssh."""
    here = cfg.computer or ("mac" if machine else next((pc.name for pc in pcs if not pc.host), "here"))
    rows, seen = [], set()
    for name, group in [(here, runners)] + [(pc.name, pc.runner_list()) for pc in pcs
                                            if pc.reachable() and hasattr(pc, "runner_list")]:
        for runner in group:
            if runner.name not in seen:
                seen.add(runner.name)
                rows.append((name, runner))
    return rows


def red(runs):
    """The workflows whose newest finished run failed: not an old failure that a later run made good."""
    newest = {}
    for run in sorted(runs or [], key=lambda run: run.get("createdAt", ""), reverse=True):
        if run.get("status") == "completed":
            newest.setdefault((run.get("repo"), run.get("workflowName")), run)
    return [run for run in newest.values() if run.get("conclusion") in FAILED]


def needs(queue, pcs, rows):
    """What asks for a person, other than a request (that has its own box): a red workflow, a computer that
    does not answer, a runner that is stopped. The worst first."""
    said = [(f"{run['workflowName']} red on {run.get('headBranch', '')} · {run.get('repo', '').split('/')[-1]} · "
             f"{ago(moment(run.get('createdAt', ''), STAMP))} · ↑↓ then l for its log", "bad") for run in red(queue.runs)]
    for pc in pcs:
        if getattr(pc, "failed", False) and not pc.reachable():
            why = getattr(pc, "why", "")
            said.append((f"{pc.name} not answering" + (f": {head_why(why)}" if why else ""), "warm"))
    said += [(f"{runner.name} on {where} is stopped · s starts it", "warm") for where, runner in rows
             if runner.state()[0] in ("stopped", "not set up")]
    return said


def vitals(canvas, y, x, name, now, history, width=0):
    """A computer in one line: CPU as a graph and a number, GPU, memory as a meter, how hot or what it draws;
    and, where there is room, what keeps its processor busy, as the MACHINES page says it."""
    canvas.put(y, x + 2, name[:13], "plain")
    graph(canvas, y, x + 16, 10, 1, history)
    for at, value in ((x + 27, now.get("cpu")), (x + 33, now.get("gpu"))):
        canvas.put(y, at, "  —" if value is None else f"{value:3.0f}%", "dim" if value is None else heat(value / 100))
    used = now.get("memory")
    if used:
        meter(canvas, y, x + 40, 10, used[0] / used[1])
        canvas.put(y, x + 51, f"{used[0]:.0f}/{used[1]:.0f} GB", "plain")
    watts = (now.get("power") or {}).get("watts")
    extra = f"{now['cpu_temp']:.0f} °C" if now.get("cpu_temp") is not None else f"{watts:.0f} W" if watts is not None else ""
    canvas.put(y, x + 62, extra, "plain")
    if width >= 90:
        canvas.put(y, x + 74, "   ".join(f"{program} {share} %" for program, share in now.get("top") or [])[:width - 75], "plain")


def runner_rows(canvas, y, x, width, rows, queue):
    """Every runner: its mark, name, computer, what it does (a busy one's meter and step), how long."""
    name_w = min(20, max([9] + [len(runner.name) for _, runner in rows]) + 1)
    where_w = min(14, max([8] + [len(where) for where, _ in rows]) + 2)
    states = [runner.state() for _, runner in rows]
    busy = sum(1 for state in states if state[0] == "running")
    failed = any(state[3] and "fail" in state[3] and state[0] != "running" for state in states)
    state_at = 3 + name_w + where_w
    band(canvas, y, x, width, "RUNNERS", ((3 + name_w, "COMPUTER"), (state_at, "STATE")), f"{busy} of {len(rows)} busy",
         "bad" if failed else None)
    for line, ((where, runner), (state, job, since, last)) in enumerate(zip(rows, states), start=y + 1):
        job_now = queue.jobs.get(runner.name) if state == "running" else None
        style = "strong" if state == "running" else "dim" if state in ("stopped", "not set up") else "plain"
        canvas.put(line, x + 1, spin(MARKS["running"]) if state == "running" else MARKS.get(state, "·"),
                   "warm" if state == "running" else style)
        canvas.put(line, x + 3, runner.name[:name_w - 1], style)
        canvas.put(line, x + 3 + name_w, where[:where_w - 1], "label")
        when = ago(since)
        room = width - state_at - len(when) - 3
        if job_now:
            share, steps, left = progress(job_now)
            meter(canvas, line, x + state_at, 12, share, "warm", scan=True)
            canvas.put(line, x + state_at + 13, f"{steps}{' · ' + left if left else ''}"[:max(0, room - 13)], "plain")
        else:
            words = f"Running {job}" if state == "running" else WORDS.get(state, state)
            canvas.put(line, x + state_at, words[:room], style)
            if last and state != "running" and len(words) + 8 < room:
                canvas.put(line, x + state_at + len(words), " · last ", "dim")
                canvas.put(line, x + state_at + len(words) + 8, last[:room - len(words) - 8],
                           "bad" if "fail" in last else "plain")
        canvas.put(line, x + width - 1 - len(when), when, "label")
    return y + 1 + len(rows)


def loading(canvas, y, width, words):
    """A segmented bar that fills and starts again, while something is asked."""
    canvas.put(y, (width - len(words)) // 2, words, "label")
    lit = int(time.time() * 10) % 31 if MOTION[0] else 15
    canvas.put(y + 1, (width - 30) // 2, "▌" * lit, "strong")
    canvas.put(y + 1, (width - 30) // 2 + lit, "▌" * (30 - lit), "empty")


def deck(canvas, cfg, runners, queue, machine, picked, pcs, health):
    width, height = canvas.width, canvas.height
    rows = every_runner(cfg, runners, machine, pcs)
    y = 2
    for at, (words, style) in enumerate(needs(queue, pcs, rows)[:3]):
        if at == 0:
            canvas.put(y, 0, " NEEDS_YOU ", "title-bad" if style == "bad" else "title-warm")
        canvas.put(y, 13, "■ " + words[:width - 15], style)
        y += 1
    y += 1 if y > 2 else 0
    # Left, where there is the room: four numbers, big, that count up when the page opens. Right: every runner,
    # then each computer in a line.
    wide = width >= 100
    x = 31 if wide else 0
    w = width - x
    top = y
    if wide:
        up = ease(progress_of("page", 0.7))

        def count(n):
            return str(round(n * up))
        busy = sum(1 for _, runner in rows if runner.state()[0] == "running")
        reds = red(queue.runs)
        stats = (("BUSY", f"{count(busy)}/{len(rows)}", "warm" if busy else "strong"),
                 ("RED", count(len(reds)), "bad" if reds else "strong"),
                 ("WAITING", count(len(queue.requests)), "warm" if queue.requests else "strong"),
                 ("RUNS", count(len(queue.runs or [])), "strong"))
        for at, (label, value, style) in enumerate(stats):
            sy, sx = y + (at // 2) * 5, 1 + (at % 2) * 14
            canvas.put(sy, sx, label, "label")
            big(canvas, sy + 1, sx, value, style)
    if rows:
        y = runner_rows(canvas, y, x, w, rows, queue) + 1
    computers = ([machine] if machine else []) + [pc for pc in pcs if pc.reachable()]
    if computers:
        band(canvas, y, x, w, "MACHINES", ((16, "CPU"), (33, "GPU"), (40, "RAM"), (62, "HEAT/POWER")) + (((74, "BUSY"),) if w >= 90 else ()) if w >= 70 else ())
        for line, pc in enumerate(computers, start=y + 1):
            name = getattr(pc, "name", None) or cfg.computer or getattr(pc, "title", "mac")
            vitals(canvas, line, x, name, pc.now, pc.cpu, w)
        y += 1 + len(computers)
    y = max(y, top + 10 if wide else y) + 1
    # Below: what waits for a yes never gives way; then the builds, the health, and the runs, which give way first.
    if queue.requests:
        y = requests_box(canvas, y, width, queue.requests, picked, queue.working,
                         repo_labels(cfg.repos) if len(cfg.repos) > 1 else None)
    here = recent_builds()
    if here and height - 3 - y >= 2 + min(5, len(here)) + 3:
        y = builds_box(canvas, y, width, here, "BUILDS")
    for pc in pcs:
        if pc.reachable() and pc.now.get("builds") and height - 3 - y >= 5:
            y = builds_box(canvas, y, width, pc.now["builds"], f"BUILDS · {pc.name}")
    if height_of(health) and height - 3 - y >= height_of(health) + 3:
        y = health_box(canvas, y, width, health, picked)
    room = height - 3 - y
    if not queue.runs and queue.problem and room >= 3:
        frame(canvas, y, 0, 3, width, "RUNS", "no runs", "warm")
        canvas.put(y + 1, 2, queue.problem[:width - 4], "warm")
    elif queue.runs is None and cfg.repos and room >= 3:
        # Not a silent gap while gh is first asked: it takes a few seconds.
        frame(canvas, y, 0, 3, width, "RUNS", "reading")
        canvas.put(y + 1, 2, spin("…"), "warm")
        canvas.put(y + 1, 4, f"asking GitHub for the last runs of {', '.join(cfg.repos)}"[:width - 6], "dim")
    elif queue.runs and room >= 3:
        github_box(canvas, y, width, queue.runs[:room - 2], cfg.repos, picked, queue.working,
                   getattr(queue, "on", None), time.time() - queue.at if getattr(queue, "at", None) else None)
    if height >= 12:
        canvas.put(height - 2, 1, "TOTAL", "label")
        canvas.put(height - 2, 8, f"{len(queue.runs or [])} RUNS · {len(cfg.repos)} REPOSITORIES · {len(rows)} RUNNERS"[:width - 9], "plain")


def took(step):
    try:
        start, end = (moment(step[k], STAMP) for k in ("startedAt", "completedAt"))
        seconds = end - start
        return "" if seconds < 0 else f"{seconds:.0f} s" if seconds < 60 else f"{seconds / 60:.0f} min"
    except (KeyError, TypeError, ValueError):
        return ""


LIVE_STAMP = re.compile(r"^\ufeff?\d{4}-\d\d-\d\dT[\d:.]+Z ?")
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def live_log(canvas, y, x, width, height, on, runners):
    """Under the steps of a run that goes on: what its job prints now, the newest lines at the foot, read
    from the runner's own folder. One line instead where the runner is not on this computer, or has
    nothing written yet. The colours of the job are not drawn; what it made bold is."""
    runner = next((runner for runner in runners if runner.name in on.split(", ")), None)
    lines = runner.live() if runner else None
    canvas.put(y, x + 1, "LIVE", "label")
    if lines is None:
        canvas.put(y, x + 10, ("nothing printed yet" if runner else "the job is not on this computer: no live log here")[:width - 11], "dim")
        return
    canvas.put(y, x + 10, runner.name[:width - 11], "plain")
    shown = []
    for raw in lines:
        # A line that was drawn over itself (a progress bar) is its last state.
        said = LIVE_STAMP.sub("", raw).rstrip("\r").split("\r")[-1]
        text = clean(ANSI.sub("", said).expandtabs(4)).rstrip()
        if text:
            shown.append((text, "bad" if text.startswith("##[error]") else "strong" if "\x1b[1m" in said else "plain"))
    for at, (text, style) in enumerate(shown[-(height - 1):], start=y + 1):
        canvas.put(at, x + 1, text[:width - 2], style)


def manifest(canvas, cfg, queue, picked, runners=()):
    """The runs as a list at the left; at the right the chosen one: its result as a tag, its name, what it is
    of, and its jobs and steps as a trace, the one that failed or runs in the middle; and under them, while
    it goes on, what its job prints."""
    width, height = canvas.width, canvas.height
    runs = queue.runs or []
    if queue.runs is None and not queue.problem:
        loading(canvas, height // 2 - 1, width, "RETRIEVING RUNS FROM GITHUB")
        return
    left = min(58, width // 2)
    labels = repo_labels(cfg.repos)
    # The repository's column only where there is room for it and a workflow's name.
    repo_at = left - 38 if left >= 50 else None
    name_w = (repo_at or left - 24) - 4
    band(canvas, 2, 0, left, "RUNS", (((repo_at, "REPO"),) if repo_at else ()) + ((left - 24, "RESULT"),), "AGE")
    chosen = next((run for run in runs if run.get("databaseId") == picked), runs[0] if runs else None)
    for line, run in enumerate(runs[:height - 5], start=3):
        conclusion = run.get("conclusion") or (run.get("status") or "").replace("_", " ")
        style = "picked" if run is chosen and picked is not None else None
        if style:
            canvas.put(line, 0, " " * left, style)
        canvas.put(line, 1, RESULTS.get(conclusion, spin("…")),
                   style or {"success": "good"}.get(conclusion, "bad" if conclusion in FAILED else "warm"))
        canvas.put(line, 3, run.get("workflowName", "")[:name_w], style or "plain")
        if repo_at:
            canvas.put(line, repo_at, labels.get(run.get("repo"), "")[:13], style or "label")
        canvas.put(line, left - 24, conclusion.upper()[:11], style or ("bad" if conclusion in FAILED else "plain"))
        age = ago(moment(run.get("createdAt", ""), STAMP))
        canvas.put(line, left - 1 - len(age), age, style or "label")
    canvas.put(height - 2, 1, "TOTAL", "label")
    canvas.put(height - 2, 8, f"{len(runs)} RUNS", "plain")
    if not chosen:
        canvas.put(4, 2, (queue.problem or "no runs yet")[:left - 4], "warm")
        return
    x, w = left + 2, width - left - 2
    band(canvas, 2, x, w, "RUN", (), f"#{chosen['databaseId']}")
    conclusion = chosen.get("conclusion") or chosen.get("status", "")
    tone = "title-bad" if conclusion in FAILED else "title" if conclusion == "success" else "title-warm"
    canvas.put(4, x + 1, f" {conclusion.upper().replace('_', ' ')} ", tone)
    canvas.put(5, x + 1, chosen.get("workflowName", "").upper()[:w - 2], "strong")
    got = run_detail(chosen) or {}
    facts = (("TITLE", got.get("displayTitle", "")), ("REPO", chosen.get("repo", "")), ("BRANCH", chosen.get("headBranch", "")),
             ("COMMIT", chosen.get("headSha", "")[:7]), ("EVENT", got.get("event", "")),
             ("RUNNER", (getattr(queue, "on", None) or {}).get(chosen["databaseId"], "")),
             ("STARTED", ago(moment(chosen.get("createdAt", ""), STAMP)) + " ago"))
    line = 7
    for label, value in facts:
        if value and line < height - 3:
            canvas.put(line, x + 1, label, "label")
            canvas.put(line, x + 10, str(value)[:w - 11], "plain")
            line += 1
    line += 1
    if got.get("jobs") is None:
        canvas.put(line, x + 1, spin("…") + " asking GitHub for the steps", "dim")
        return
    trace = []
    for job in got["jobs"]:
        trace.append(("job", job.get("name", ""), job.get("conclusion") or job.get("status", ""), took(job)))
        trace += [("step", step.get("name", ""), step.get("conclusion") or step.get("status", ""), took(step))
                  for step in job.get("steps", [])]
    room = height - 2 - line
    if room <= 0 or not trace:
        return
    # Which runner has it, once GitHub has said so: the live log needs half of the room then.
    on = (getattr(queue, "on", None) or {}).get(chosen["databaseId"], "")
    live = chosen.get("status") == "in_progress" and on and not on.startswith("waiting for") and room >= 8
    if live:
        room //= 2
    stuck = next((at for at, item in enumerate(trace) if item[2] not in ("success", "skipped", "completed")), len(trace) - 1)
    first = max(0, min(stuck - room // 2, len(trace) - room))
    for kind, name, state, length in trace[first:first + room]:
        if kind == "job":
            canvas.put(line, x + 1, name.upper()[:w - 10], "label")
        else:
            mark, style = (("■", "warm") if state == "success" else ("■", "bad") if state in FAILED
                           else ("□", "dim") if state == "skipped" else (spin("■"), "strong"))
            canvas.put(line, x + 2, mark, style)
            canvas.put(line, x + 4, name[:w - 14], "bad" if state in FAILED else "plain" if state == "success" else "dim")
        canvas.put(line, x + w - 1 - len(length), length, "label")
        line += 1
    if live and height - 2 - line >= 3:
        live_log(canvas, line + 1, x, w, height - 3 - line, on, runners)


def head(canvas, cfg, runners, queue, health, page):
    """The name, the page, the health's word; at the right what is to be done, whether the machine stays
    awake, the pages and the time. Where it is short, the time goes first, then the page's name, then the
    pages' names (their numbers stay), then the pages."""
    width = canvas.width
    canvas.put(0, 0, f" {NAME_CHIP} ", "title")
    beat = int(time.time() * 2) if MOTION[0] else 1
    canvas.put(0, 12, "".join(GLYPH["unlit"] if (beat + at) % 4 == 0 else GLYPH["lit"] for at in range(3)), "glitch")
    word, style = health.words() if health else ("", "")
    must = []
    if getattr(queue, "update_ready", False):
        must.append(("update ready · u", "warm"))
    if runners:
        awake = alive(cfg.awake)
        must.append((("awake" if awake else "may sleep") + (" · notifying" if alive(cfg.watch) else ""), "good" if awake else "warm"))
    title = next(long for n, _, long in PAGES if n == page)
    full = [(f" {n} {short} ▸ ", "pop-on" if n == page else "key") for n, short, _ in PAGES]
    small = [(f" {n} ", "pop-on" if n == page else "key") for n, _, _ in PAGES]
    clock = (time.strftime("%H:%M:%S"), "label")
    for named, chips, timed in ((True, full, True), (True, full, False), (False, full, False), (False, small, False),
                                (False, [], False)):
        left = 17 + (len(title) + 2 if named else 0) + (len(word) + 2 if word else 0)
        parts = must + ([("chips", "")] if chips else []) + ([clock] if timed else [])
        need = sum((sum(len(c) + 1 for c, _ in chips) if text == "chips" else len(text)) + 3 for text, _ in parts)
        if left + need <= width + 3:
            break
    at = 17
    if named:
        canvas.put(0, at, title, "strong")
        at += len(title) + 2
    if word:
        canvas.put(0, at, word, style)
    edge = width
    for text, part_style in reversed(parts):
        if text == "chips":
            for chip, chip_style in reversed(chips):
                edge -= len(chip)
                canvas.put(0, edge, chip, chip_style)
                edge -= 1
            edge -= 2
        else:
            edge -= len(text)
            canvas.put(0, edge, text, part_style)
            edge -= 3


def paint(canvas, cfg, runners, queue, machine, shown, note, picked=None, dialog=None, pcs=(), health=None, page=1):
    """The screen: the head, the page, the foot; a question over all of it. On a terminal a margin goes
    round it; --status's text has none."""
    screen = canvas
    if isinstance(canvas, Screen):
        canvas = Inset(canvas)
    width, height = canvas.width, canvas.height
    head(canvas, cfg, runners, queue, health, page)
    if page == 2:
        manifest(canvas, cfg, queue, picked, runners)
    elif page == 3:
        logs = with_remote(runners, pcs)
        if logs and height >= 6:
            log_box(canvas, 2, width, height - 3, logs, shown % len(logs))
        elif not logs:
            canvas.put(3, 1, "No runner has a log to show here.", "dim")
    elif page == 4:
        computers = ([machine] if machine else []) + [pc for pc in pcs if pc.reachable()]
        tall = max(1, (height - 3 - 5 * len(computers)) // (2 * max(1, len(computers))) + 1) if width >= 96 else 1
        y = 2
        for pc in computers:
            if y + 5 > height - 1:
                break
            y = mac_box(canvas, y, width, pc, tall) if pc is machine or getattr(pc, "kind", "") == "macos" \
                else pc_box(canvas, y, width, pc, tall)
        if not computers:
            canvas.put(3, 1, "No computer answers.", "dim")
    else:
        deck(canvas, cfg, runners, queue, machine, picked, pcs, health)
    decode(screen, progress_of("page", 0.45))
    picking = (("field" if "field" in dialog else "dialog") if dialog else None if picked is None
               else "request" if picked < 0 else "issue" if picked >= ISSUE_ROW else "run")
    if dialog:
        popup(screen, dialog)
    # Last: its keys are read while a question is up too.
    footer(canvas, height - 1, width, "" if dialog else note, picking, page)


def moving(runners, queue, pcs=()):
    """Whether anything on the screen moves: a runner with a job, a run or a build that is going,
    a thing being done. The screen is drawn four times a second then, else once."""
    if getattr(queue, "working", None) or any(run.get("status") == "in_progress" for run in queue.runs or []):
        return True
    if queue.runs is None and getattr(queue, "cfg", None) and queue.cfg.repos and not queue.problem:
        return True
    return any(runner.state()[0] == "running" for runner in with_remote(runners, pcs))
