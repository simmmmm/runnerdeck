"""The opening: a sign of three runners, the name out of noise, a cursor that blinks, a bar that retrieves,
then an orange wipe over the screen, and the screen starts. It takes about a second and a half, and any key
skips it. It draws only; nothing waits on it. The wipe is also how the screen leaves."""
import random
import time
from .terminal import GLYPH, MOTION, Screen

# Three rows of heavy lines: "RUNNERDECK", 39 columns wide.
LETTERS = {"R": ("┏━┓", "┣┳┛", "╹┗╸"), "U": ("╻ ╻", "┃ ┃", "┗━┛"), "N": ("┏┓╻", "┃┗┫", "╹ ╹"), "E": ("┏━╸", "┣╸ ", "┗━╸"),
           "D": ("┳━┓", "┃ ┃", "┻━┛"), "C": ("┏━╸", "┃  ", "┗━╸"), "K": ("╻ ╻", "┣┻┓", "╹ ╹")}
LOGO = [" ".join(LETTERS[letter][row] for letter in "RUNNERDECK") for row in range(3)]
TAGLINE = "RUNNERS · MACHINES · RUNS"
DONE = 22      # from this frame on the picture is whole
WIPE = 24      # the wipe's first frame
FRAMES = 30


def facts(cfg, runners, pcs):
    """What the opening says of this deck: only what is true of the config."""
    names = [f"{len(cfg.repos)} repositor{'y' if len(cfg.repos) == 1 else 'ies'}"]
    if runners:
        names.append(f"{len(runners)} runner{'' if len(runners) == 1 else 's'}")
    if pcs:
        names.append(f"{len(pcs)} other computer{'' if len(pcs) == 1 else 's'}")
    return " · ".join(names)


def sign():
    """Three runners as slabs, standing down like a deck."""
    slab = GLYPH["mark"]
    return [slab * 3, slab * 3, slab * 2 + " " * len(slab), slab + " " * (2 * len(slab))]


def paint(canvas, step, said="", rng=None):
    """One frame. `step` counts from 0; from DONE on the picture is whole, from WIPE on it is the wipe."""
    rng = rng or random.Random(step)
    width, height = canvas.width, canvas.height
    if step >= WIPE:
        # Orange from the top, a few dark dots in it, a dithered edge running down after it.
        reach = (step - WIPE + 1) * height // 4
        dot, edge = (GLYPH["noise"][0], "▓▒") if GLYPH["braille"] else ("#", "#=")
        for row in range(height):
            if row < reach:
                canvas.put(row, 0, "".join(dot if rng.random() < 0.08 else " " for _ in range(width)), "wipe")
            elif row < reach + 2:
                canvas.put(row, 0, "".join(rng.choice(edge) for _ in range(width)), "cross")
        return
    left, top = (width - len(LOGO[0])) // 2, max(0, (height - 14) // 2)
    mark = sign()
    for row in range(min(len(mark), step + 1)):
        canvas.put(top + row, (width - len(mark[0])) // 2, mark[row], "logo")
    # The edge of what is decoded runs over the name: left of it the letters, right of it noise.
    reach = (step - 3) * 6
    for row, line in enumerate(LOGO):
        for at, character in enumerate(line):
            if at < reach - 6:
                canvas.put(top + 5 + row, left + at, character, "logo")
            elif at < reach and character != " ":
                canvas.put(top + 5 + row, left + at, rng.choice(GLYPH["noise"]), "glitch")
    if step < 10:
        canvas.put(top + 9, width // 2, "_" if step % 4 < 2 else " ", "strong")
        return
    label = "RETRIEVING DECK DATA" if step < DONE - 3 else TAGLINE
    canvas.put(top + 9, (width - len(label)) // 2, label, "label")
    lit = min(30, (step - 9) * 3)
    start = (width - 36) // 2
    canvas.put(top + 10, start, "▌" * lit, "strong")
    canvas.put(top + 10, start + lit, "▌" * (30 - lit), "empty")
    canvas.put(top + 10, start + 32, f"{round(lit / 30 * 100):3d}%", "strong" if lit == 30 else "plain")
    if step >= DONE - 3:
        canvas.put(top + 12, (width - len(said)) // 2, said, "dim")


def play(window, said=""):
    """The opening on this terminal. A key ends it at once (and is used up by that). Too small a
    screen gets none."""
    height, width = window.size()
    if width < 48 or height < 15:
        return
    for step in range(FRAMES):
        canvas = Screen(window)
        paint(canvas, step, said)
        canvas.flush()
        if window.key(0.05) != -1:
            return


def wipe(window):
    """The orange wipe alone, as the screen leaves. Nothing where nothing moves."""
    if not MOTION[0]:
        return
    for step in range(WIPE, FRAMES):
        canvas = Screen(window)
        paint(canvas, step)
        canvas.flush()
        time.sleep(0.04)
