"""The opening: the logo comes out of noise, a bar fills, and the screen starts.
It takes about a second, and any key skips it. It draws only; nothing waits on it."""
import random
from .terminal import Screen

# Three rows of box-drawing letters: "runnerdeck", 39 columns wide.
LETTERS = {
    "r": ("╦═╗", "╠╦╝", "╩╚═"), "u": ("╦ ╦", "║ ║", "╚═╝"), "n": ("╔╗╔", "║║║", "╝╚╝"),
    "e": ("╔═╗", "║╣ ", "╚═╝"), "d": ("╔╦╗", " ║║", "═╩╝"), "c": ("╔═╗", "║  ", "╚═╝"),
    "k": ("╦╔═", "╠╩╗", "╩ ╩"),
}
LOGO = [" ".join(LETTERS[letter][row] for letter in "runnerdeck") for row in range(3)]
TAGLINE = "runners · machines · runs"
NOISE = "░▒▓╳#01/\\|"
STEPS = 16     # frames; the pause between them is set in play()
HOLD = 5       # frames the finished picture stays


def facts(cfg, runners, pcs):
    """What the opening says of this deck: only what is true of the config."""
    names = [f"{len(cfg.repos)} repositor{'y' if len(cfg.repos) == 1 else 'ies'}"]
    if runners:
        names.append(f"{len(runners)} runner{'' if len(runners) == 1 else 's'}")
    if pcs:
        names.append(f"{len(pcs)} other computer{'' if len(pcs) == 1 else 's'}")
    return " · ".join(names)


def paint(canvas, step, said="", rng=None):
    """One frame. `step` counts from 0; from STEPS on the picture is whole. The edge of what is
    decoded moves over the logo as a bright bar, left of it the letters, right of it noise."""
    rng = rng or random.Random(step)
    width = len(LOGO[0])
    left = (canvas.width - width) // 2
    top = max(0, (canvas.height - 9) // 2)
    reach = min(1.0, step / (STEPS - 4)) * (width + 12)
    for row, line in enumerate(LOGO):
        for at, character in enumerate(line):
            here = reach - row * 2
            if at < here - 4:
                canvas.put(top + row, left + at, character, "logo")
            elif at < here:
                canvas.put(top + row, left + at, rng.choice(NOISE), "glitch")
            elif at < here + 1 and step < STEPS:
                canvas.put(top + row, left + at, "▌", "strong")
    ready = min(1.0, max(0, step - 4) / (STEPS - 6))
    canvas.put(top + 4, (canvas.width - len(TAGLINE)) // 2, TAGLINE[:round(len(TAGLINE) * ready)], "label")
    bar = 28
    filled = round(min(1.0, step / (STEPS - 1)) * bar)
    start = (canvas.width - bar - 8) // 2
    canvas.put(top + 6, start, "[" + "█" * filled + "░" * (bar - filled) + "]", "edge")
    canvas.put(top + 6, start + bar + 3, f"{round(filled / bar * 100):3d}%", "strong" if filled == bar else "plain")
    if step >= STEPS - 4:
        canvas.put(top + 8, (canvas.width - len(said)) // 2, said, "dim")


def play(window, said=""):
    """The opening on this terminal. A key ends it at once (and is used up by that). Too small a
    screen gets none."""
    height, width = window.size()
    if width < len(LOGO[0]) + 4 or height < 11:
        return
    for step in range(STEPS + HOLD):
        canvas = Screen(window)
        paint(canvas, step, said)
        canvas.flush()
        if window.key(0.045) != -1:
            return
