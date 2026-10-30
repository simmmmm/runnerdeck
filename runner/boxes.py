"""The boxes of the screen, and the screen made of them."""
import os
import time
from .util import STAMP, ago, moment
from .system import alive
from .github import row_of
from .machines import power, run, watts
from .terminal import frame, heat, meter, popup, right, spark


MARKS = {"running": "●", "listening": "○", "starting": "◌"}


WORDS = {"listening": "Listening", "starting": "Starting…", "stopped": "Stopped", "not set up": "Not set up"}


RESULTS = {"success": "✓", "failure": "✗", "cancelled": "–", "skipped": "–"}


def mac_box(canvas, y, width, machine):
    """CPU and GPU as graphs, memory as a meter; beside them, or under them
    where the screen is narrow, what the battery says and how hot."""
    now = machine.now
    wide = width >= 96
    height = 5 if wide else 8
    frame(canvas, y, 0, height, width, "mac", f"load {os.getloadavg()[0]:.1f} · {os.cpu_count()} cores")
    half = (width - 4) // 2 - 1 if wide else width - 4
    row = y + 1
    for name, value, history in (("CPU", now.get("cpu"), machine.cpu), ("GPU", now.get("gpu"), machine.gpu)):
        canvas.put(row, 2, name, "label")
        spark(canvas, row, 7, half - 13, history)
        if value is None:
            canvas.put(row, half - 4, "  —", "dim")
        else:
            canvas.put(row, half - 4, f"{value:3.0f} %", heat(value / 100))
        row += 1
    used = now.get("memory")
    canvas.put(row, 2, "RAM", "label")
    if used:
        meter(canvas, row, 7, half - 22, used[0] / used[1])
        canvas.put(row, half - 13, f"{used[0]:4.1f} / {used[1]:.0f} GB", "plain")
    row = y + 1 if wide else row + 1
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


def pc_box(canvas, y, width, pc):
    """A Linux machine as the Mac above it: CPU and GPU as graphs, memory as a meter;
    beside them, or under them, how hot it is, what the card draws, and its
    runner. A machine that does not answer says so, and shows no old numbers as
    if they were now."""
    now = pc.now if pc.reachable() else {}
    wide = width >= 96
    height = 5 if wide else 8
    host = pc.host.split("@")[-1] if pc.host else "here"
    if pc.reachable():
        right_side = f"{host} · load {now['load']:.1f} · {now['threads']:.0f} threads" if now.get("load") is not None else host
    else:
        right_side = f"{host} · not answering"
    frame(canvas, y, 0, height, width, pc.name, right_side)
    half = (width - 4) // 2 - 1 if wide else width - 4
    row = y + 1
    for name, value, history in (("CPU", now.get("cpu"), pc.cpu), ("GPU", now.get("gpu"), pc.gpu)):
        canvas.put(row, 2, name, "label")
        spark(canvas, row, 7, half - 13, history if pc.reachable() else [])
        if value is None:
            canvas.put(row, half - 4, "  —", "dim")
        else:
            canvas.put(row, half - 4, f"{value:3.0f} %", heat(value / 100))
        row += 1
    used = now.get("memory")
    canvas.put(row, 2, "RAM", "label")
    if used:
        meter(canvas, row, 7, half - 22, used[0] / used[1])
        canvas.put(row, half - 13, f"{used[0]:4.1f} / {used[1]:.0f} GB", "plain")
    row = y + 1 if wide else row + 1
    x = half + 4 if wide else 2
    canvas.put(row, x, "Heat", "label")
    # Ryzen's Tctl runs in the 80s under a build and holds to 95; the card's
    # edge sensor is cooler than its junction.
    cpu_temp, gpu_temp = now.get("cpu_temp"), now.get("gpu_temp")
    canvas.put(row, x + 9, f"CPU {cpu_temp:.0f} °C" if cpu_temp is not None else "CPU —", hot(cpu_temp, 80, 90))
    canvas.put(row, x + 21, f"GPU {gpu_temp:.0f} °C" if gpu_temp is not None else "GPU —", hot(gpu_temp, 75, 85))
    row += 1
    canvas.put(row, x, "Card", "label")
    power, vram = now.get("gpu_power"), now.get("vram")
    canvas.put(row, x + 9, f"{power:.0f} W" if power is not None else "—", "strong" if power is not None else "dim")
    if vram:
        canvas.put(row, x + 16, f"VRAM {vram[0]:.1f} / {vram[1]:.0f} GB", "plain")
    row += 1
    if not pc.service:
        return y + height
    state, job, since, last = pc.state()
    canvas.put(row, x, "Runner", "label")
    words = f"Running {job}" if state == "running" else {**WORDS, "unreachable": "Unreachable"}.get(state, state)
    canvas.put(row, x + 9, MARKS.get(state, "·"), "good" if state == "running" else "dim")
    canvas.put(row, x + 11, words[:max(0, width - x - 24)], "strong" if state == "running" else "dim" if state in ("stopped", "unreachable") else "plain")
    right(canvas, row, width, ago(since) if state in ("running", "listening") else "", "label")
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


def runners_box(canvas, y, width, runners, queue):
    """Each runner: what it is doing in its own words, the last result in
    its colour, and a busy one's progress beside it, or under it where the
    screen is narrow."""
    wide = width >= 110
    rows = []
    for runner in runners:
        state, job, since, last = runner.state()
        busy = queue.jobs.get(runner.name) if state == "running" else None
        rows.append((runner, state, job, since, last, busy))
    height = 2 + len(rows) + sum(1 for row in rows if row[5] and not wide)
    busy_count = sum(1 for row in rows if row[1] == "running")
    frame(canvas, y, 0, height, width, "runners", f"{busy_count} of {len(rows)} busy")
    line = y + 1
    for runner, state, job, since, last, busy in rows:
        style = "strong" if state == "running" else "dim" if state in ("stopped", "not set up") else "plain"
        canvas.put(line, 2, MARKS.get(state, "·"), "good" if state == "running" else style)
        canvas.put(line, 4, runner.name, style)
        words = f"Running {job}" if state == "running" else WORDS[state]
        canvas.put(line, 11, words, style)
        if last and state != "running":
            canvas.put(line, 11 + len(words), " · last ", "dim")
            canvas.put(line, 19 + len(words), last, "bad" if "fail" in last else "good" if "succeed" in last else "plain")
        when = ago(since)
        if busy:
            share, steps, left = progress(busy)
            at, place = (line, 34) if wide else (line + 1, 11)
            meter(canvas, at, place, 16, share, "good")
            canvas.put(at, place + 18, steps[:max(0, width - place - 22 - len(left) - len(when) - 6)], "dim")
            if left:
                when = f"{left} · {when}" if wide else when
                if not wide:
                    right(canvas, at, width, left, "label")
        right(canvas, line, width, when, "label")
        line += 2 if busy and not wide else 1
    return y + height


def github_box(canvas, y, width, runs, repos, picked=None, working=None):
    working = working or {}
    many = len({run.get("repo") for run in runs}) > 1
    frame(canvas, y, 0, 2 + len(runs), width, "github", ", ".join(repos) if len(", ".join(repos)) < width - 16 else f"{len(repos)} repositories")
    for line, run in enumerate(runs, start=y + 1):
        doing = working.get(run.get("databaseId"))
        if run.get("databaseId") == picked:
            canvas.put(line, 1, "▸" + " " * (width - 3), "picked")
            canvas.put(line, 4, run.get("workflowName", "")[:12], "picked")
            canvas.put(line, 17, run.get("headBranch", "")[:24], "picked")
            canvas.put(line, 42, run.get("headSha", "")[:7], "picked")
            if many:
                canvas.put(line, 50, run.get("repo", "").split("/")[-1][:16], "picked")
            word = f"{doing}…" if doing else run.get("conclusion") or (run.get("status") or "").replace("_", " ")
            right(canvas, line, width, f"{word} · {ago(moment(run.get('createdAt', ''), STAMP))}", "picked")
            continue
        done = run.get("status") == "completed"
        conclusion = run.get("conclusion") or ""
        mark = RESULTS.get(conclusion, "·") if done else "…" if run.get("status") == "in_progress" else "·"
        style = {"success": "good", "failure": "bad"}.get(conclusion, "dim") if done else "warm"
        canvas.put(line, 2, mark, style)
        canvas.put(line, 4, run.get("workflowName", "")[:12], "strong" if not done else "plain")
        canvas.put(line, 17, run.get("headBranch", "")[:24], "dim")
        canvas.put(line, 42, run.get("headSha", "")[:7], "dim")
        if many:
            canvas.put(line, 50, run.get("repo", "").split("/")[-1][:16], "dim")
        word = f"{doing}…" if doing else conclusion if done else (run.get("status") or "").replace("_", " ")
        when = ago(moment(run.get("createdAt", ""), STAMP))
        right(canvas, line, width, f"{word} · {when}", "warm" if doing else style if style != "dim" else "label")
    return y + 2 + len(runs)


def requests_box(canvas, y, width, requests, picked=None, working=None):
    working = working or {}
    frame(canvas, y, 0, 2 + len(requests), width, "waiting for you", "a: start · d: decline")
    for line, request in enumerate(requests, start=y + 1):
        chosen = row_of(request) == picked
        doing = working.get(row_of(request))
        if chosen:
            canvas.put(line, 1, "▸" + " " * (width - 3), "picked")
        else:
            canvas.put(line, 2, "?", "warm")
        canvas.put(line, 4, request["workflow"][:12], "picked" if chosen else "strong")
        canvas.put(line, 17, request["branch"][:24], "picked" if chosen else "dim")
        canvas.put(line, 42, request["sha"][:7], "picked" if chosen else "dim")
        words = f"{doing}…" if doing else request["note"]
        canvas.put(line, 50, words[:max(0, width - 52)], "picked" if chosen else "warm" if doing else "label")
    return y + 2 + len(requests)


def log_box(canvas, y, width, height, runner):
    """The log of the runner shown, its newest lines at the foot; a job's
    start in white, its end in the colour of how it ended."""
    frame(canvas, y, 0, height, width, f"log · {runner.name}", "tab: another")
    lines = [line for line in runner.tail() if line.strip()][-(height - 2):] if height > 2 else []
    for at, line in enumerate(lines, start=y + 1):
        style = ("bad" if "Failed" in line else "good" if "Succeeded" in line
                 else "strong" if "Running job" in line else "dim")
        canvas.put(at, 2, line[:width - 4], style)


def footer(canvas, y, width, note, picking=None):
    if note:
        canvas.put(y, 1, note[:width - 2], "warm")
        return
    x = 1
    keys = {"run": (("↑↓", "choose"), ("c", "cancel"), ("r", "run again"), ("o", "open"), ("esc", "back")),
            "request": (("↑↓", "choose"), ("enter", "start"), ("d", "decline"), ("esc", "back")),
            "dialog": (("y", "yes"), ("n", "no"), ("← →", "choose"), ("enter", "answer")),
            "field": (("enter", "set up"), ("esc", "cancel")),
            None: (("q", "quit, runners stay on"), ("s", "start"), ("x", "stop"), ("n", "new runner"), ("w", "approval"), ("tab", "next log"), ("↑↓", "runs"))}[picking]
    for key, words in keys:
        canvas.put(y, x, key, "strong")
        canvas.put(y, x + len(key) + 1, words, "label")
        x += len(key) + len(words) + 4


def paint(canvas, cfg, runners, queue, machine, shown, note, picked=None, dialog=None, pcs=()):
    """The whole screen: the head, this machine and the others, the runners,
    GitHub's last runs and a log, the log taking what is left and GitHub
    giving way first."""
    width, height = canvas.width, canvas.height
    canvas.put(0, 1, "◐ runner", "strong")
    awake = "awake" if alive(cfg.awake) else "may sleep"
    told = " · notifying" if alive(cfg.watch) else ""
    if runners:
        right(canvas, 0, width + 1, f"{awake}{told}", "good" if alive(cfg.awake) else "warm")
    y = 1
    if machine:
        y = mac_box(canvas, y, width, machine)
    for pc in pcs:
        y = pc_box(canvas, y, width, pc)
    if runners:
        y = runners_box(canvas, y, width, runners, queue)
    if queue.requests:
        y = requests_box(canvas, y, width, queue.requests, picked, queue.working)
    room = height - 1 - y
    if not queue.runs and queue.problem and room >= 3:
        frame(canvas, y, 0, 3, width, "github", "no runs")
        canvas.put(y + 1, 2, queue.problem[:width - 4], "warm")
        y += 3
    if queue.runs and room >= 5:
        y = github_box(canvas, y, width, queue.runs[:max(1, min(len(queue.runs), room - 7))], cfg.repos, picked, queue.working)
    if runners and height - 1 - y >= 3:
        log_box(canvas, y, width, height - 1 - y, runners[shown])
    picking = (("field" if "field" in dialog else "dialog") if dialog else None if picked is None
               else "request" if picked < 0 else "run")
    if dialog:
        popup(canvas, dialog)
    # Last: its keys are read while a popup is up too.
    footer(canvas, height - 1, width, "" if dialog else note, picking)
