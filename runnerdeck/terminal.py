"""The terminal: keys and size, how a frame is painted, and the pieces boxes are made of."""
import ctypes
import os
import shutil
import sys
import time
from .system import end

from .system import WINDOWS
try:
    import curses
except ImportError:  # Windows has none; the screen is drawn here, curses only hears the keys
    curses = None
if WINDOWS:
    import msvcrt
# curses' own numbers for the keys the screen uses, so that Windows says the same.
K_DOWN, K_UP, K_LEFT, K_RIGHT, K_BACKSPACE, K_ENTER, K_RESIZE = 258, 259, 260, 261, 263, 343, 410
K_HOME, K_END, K_DELETE = 262, 360, 330


# curses' own numbers for the keys the screen uses, so that Windows says the same.
ENTER = (10, 13, K_ENTER)


# The screen's colours by name, filled in by `colours` under curses; the
# text of --status has none, and draws an empty meter cell as a dot.
STYLE = {}


# The characters that are not plain text, by what the terminal's font can show (`glyphs`):
# --status keeps these, so that its text stays the same; the screen gets ▰▱ and braille
# graphs, or ■ and | / - \ where the font is an old one (the Linux console, Windows' conhost).
GLYPH = {"full": "█", "empty": "·", "spin": "", "braille": False, "noise": "#=/\\|_.:", "lit": "#", "unlit": ".",
         "mark": "###", "digits": False}


# Whether things move (spinners, the scan over a busy job's meter): off in --status and
# tests, off with RUNNERDECK_CALM, off where there is no colour. Set by the screen.
MOTION = [False]


BLOCKS = "▁▂▃▄▅▆▇█"


class Grid:
    """--status's screen: the same painting, as text."""

    def __init__(self, height, width):
        self.height, self.width = height, width
        self.rows = [[" "] * width for _ in range(height)]

    def put(self, y, x, text, style=""):
        if 0 <= y < self.height:
            for at, character in enumerate(text):
                if 0 <= x + at < self.width:
                    self.rows[y][x + at] = character

    def text(self):
        return "\n".join("".join(row).rstrip() for row in self.rows).rstrip()


class CursesTerminal:
    """Keys and size through curses, which is all it is used for."""

    def __init__(self, window):
        self.window = window
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        window.timeout(1000)
        # curses clears the screen once, at its first refresh: not over a frame.
        window.refresh()

    def size(self):
        return self.window.getmaxyx()

    def key(self, wait=1.0):
        """A key within `wait` seconds, or -1."""
        self.window.timeout(int(wait * 1000))
        return self.window.getch()

    def leave(self):
        curses.endwin()

    def back(self):
        self.window.clear()
        self.window.refresh()


class ConsoleTerminal:
    """The same on Windows, which has no curses: the console is told to read
    the escape sequences the screen is drawn with, the keys come from msvcrt,
    and the screen is the console's alternate one."""

    def __init__(self):
        self.shape = None

    def __enter__(self):
        kernel = ctypes.windll.kernel32
        kernel.GetStdHandle.restype = ctypes.c_void_p
        kernel.GetConsoleMode.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
        kernel.SetConsoleMode.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        self.handle = kernel.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        self.mode = mode.value if kernel.GetConsoleMode(self.handle, ctypes.byref(mode)) else None
        if self.mode is not None:
            kernel.SetConsoleMode(self.handle, self.mode | 0x0004)  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
        kernel.SetConsoleOutputCP(65001)
        self.back()
        return self

    def __exit__(self, *error):
        self.leave()
        if self.mode is not None:
            ctypes.windll.kernel32.SetConsoleMode(self.handle, self.mode)

    def size(self):
        columns, lines = shutil.get_terminal_size()
        return lines, columns

    def key(self, wait=1.0):
        """A key within `wait` seconds, or -1; a changed size is a key too."""
        end = time.time() + wait
        while time.time() < end:
            if msvcrt.kbhit():
                character = msvcrt.getwch()
                if character in ("\x00", "\xe0"):
                    return {"H": K_UP, "P": K_DOWN, "K": K_LEFT, "M": K_RIGHT, "G": K_HOME, "O": K_END, "S": K_DELETE}.get(msvcrt.getwch(), 0)
                return ord("q") if character == "\x03" else ord(character)
            if self.shape is not None and self.size() != self.shape:
                self.shape = self.size()
                return K_RESIZE
            time.sleep(0.05)
        return -1

    def leave(self):
        sys.stdout.write("\x1b[?25h\x1b[?1049l")
        sys.stdout.flush()

    def back(self):
        sys.stdout.write("\x1b[?1049h\x1b[?25l\x1b[2J")
        sys.stdout.flush()
        self.shape = self.size()


class Screen:
    """The terminal, drawn here and not through curses, which now only hears
    the keys. The Mac's Python has the curses that counts bytes: "─" and "█"
    are three to it, so boxes lost their edges and bars came out as "�". One
    frame at a time, over the last, so nothing flickers."""

    def __init__(self, window):
        self.height, self.width = window.size()
        self.rows = [[(" ", "")] * self.width for _ in range(self.height)]

    def put(self, y, x, text, style=""):
        if 0 <= y < self.height:
            for at, character in enumerate(text):
                if 0 <= x + at < self.width:
                    self.rows[y][x + at] = (character, style)

    def dim(self):
        """All of it pushed back, for what comes over it."""
        self.rows = [[(character, "under") for character, _ in row] for row in self.rows]

    def shade(self, y, x, count):
        """A shadow: what is there, darker."""
        if 0 <= y < self.height:
            for at in range(max(0, x), min(self.width, x + count)):
                self.rows[y][at] = (self.rows[y][at][0], "shadow")

    def flush(self):
        out = ["\x1b[?7l"]
        for y, row in enumerate(self.rows, start=1):
            out.append(f"\x1b[{y};1H")
            now = None
            for character, style in row:
                if style != now:
                    out.append(f"\x1b[0;{STYLE.get(style, '')}m")
                    now = style
                out.append(character)
        out.append("\x1b[0m\x1b[?7h")
        sys.stdout.buffer.write("".join(out).encode("utf-8"))
        sys.stdout.buffer.flush()


def depth(env=None):
    """How many colours the terminal has, as far as it says: 0 for none (NO_COLOR, a dumb
    terminal), 8 for the old ones (the Linux console, plain xterm), 256 for the rest."""
    env = os.environ if env is None else env
    term = env.get("TERM", "")
    if env.get("NO_COLOR") or term in ("dumb", "vt100"):
        return 0
    if WINDOWS or "256" in term or env.get("COLORTERM") in ("truecolor", "24bit") or term in ("", "alacritty", "kitty", "foot", "wezterm"):
        return 256
    return 8


def rich(env=None):
    """Whether the font has braille and ▰▱: not the Linux console's, not conhost's (Windows
    Terminal sets WT_SESSION, and has them)."""
    env = os.environ if env is None else env
    if WINDOWS:
        return bool(env.get("WT_SESSION"))
    return env.get("TERM", "") not in ("linux", "dumb", "vt100")


def glyphs(env=None):
    if rich(env):
        GLYPH.update({"full": "▰", "empty": "▱", "spin": "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏", "braille": True, "noise": "▪▫░▒/\\|_",
                      "lit": "▮", "unlit": "▯", "mark": "▐█▌", "digits": True})
    else:
        GLYPH.update({"full": "■", "empty": "·", "spin": "|/-\\", "braille": False, "noise": "#=/\\|_.:",
                      "lit": "#", "unlit": ".", "mark": "###", "digits": False})


def colours(env=None):
    """Black, off-white and grey, and one accent: orange, for what is chosen, busy or asks a look; red only
    for what is wrong. SGR's numbers; the ground is the screen's own, so that the look does not depend on
    the terminal's theme. Where the terminal has 8 colours the same names get the 8, and with none, bold
    and dim and reverse only. What is said is never in the colour alone: the numbers, the marks and the
    words are there too. `title` is a section's name as a chip, `band` the grey head of a section, `key` a
    key in the foot, `picked` the chosen row; `dlg-` the orange panel of a question, `menu` a bar of a menu."""
    levels = depth(env)
    glyphs(env)
    if levels == 256:
        ground = ";48;5;233"
        STYLE.update({
            "frame": "38;5;239", "cool": "38;5;245", "edge": "1;38;5;254", "label": "38;5;245", "plain": "38;5;254",
            "dim": "38;5;241", "strong": "1;38;5;231", "good": "38;5;254", "warm": "38;5;202", "bad": "1;38;5;196",
            "empty": "38;5;236", "logo": "1;38;5;231", "glitch": "38;5;202", "edge-bad": "1;38;5;196", "edge-warm": "1;38;5;202",
            "title": "1;38;5;233;48;5;254", "title-bad": "1;38;5;231;48;5;196", "title-warm": "1;38;5;233;48;5;202",
            "key": "1;38;5;233;48;5;250", "picked": "1;38;5;233;48;5;202", "shadow": "38;5;234;48;5;232",
            "band": "38;5;245;48;5;235", "menu": "38;5;254;48;5;236", "cross": "38;5;202", "wipe": "38;5;233;48;5;202",
            # What a question lies over, and the question: an orange panel.
            "under": "38;5;237", "pop": "38;5;233;48;5;202", "pop-strong": "1;38;5;233;48;5;202",
            "pop-frame": "38;5;233;48;5;202", "pop-off": "38;5;254;48;5;236", "pop-on": "1;38;5;233;48;5;202",
            "dlg": "38;5;233;48;5;202", "dlg-strong": "1;38;5;233;48;5;202", "dlg-dim": "38;5;88;48;5;202",
            "dlg-field": "38;5;233;48;5;166", "dlg-value": "1;38;5;233;48;5;166", "dlg-chip": "1;38;5;254;48;5;233",
            "dlg-on": "1;38;5;231;48;5;233", "dlg-off": "38;5;233;48;5;166",
        })
        for name in STYLE:
            if "48;" not in STYLE[name]:
                STYLE[name] += ground
        STYLE[""] = "38;5;254" + ground
    elif levels == 8:
        STYLE.update({
            "frame": "2;37", "cool": "37", "edge": "1;37", "label": "37", "plain": "37", "dim": "2;37", "strong": "1;37",
            "good": "37", "warm": "33", "bad": "1;31", "empty": "2;37", "logo": "1;37", "glitch": "33",
            "edge-bad": "1;31", "edge-warm": "1;33", "title": "30;47", "title-bad": "1;37;41", "title-warm": "30;43",
            "key": "30;47", "picked": "30;43", "shadow": "2", "band": "37", "menu": "37", "cross": "33", "wipe": "30;43",
            "under": "2;37", "pop": "30;43", "pop-strong": "1;30;43", "pop-frame": "30;43", "pop-off": "37", "pop-on": "30;43",
            "dlg": "30;43", "dlg-strong": "1;30;43", "dlg-dim": "30;43", "dlg-field": "4;30;43", "dlg-value": "1;4;30;43",
            "dlg-chip": "1;37;40", "dlg-on": "1;37;40", "dlg-off": "30;43",
        })
        STYLE[""] = ""
    else:
        STYLE.update({name: "" for name in ("frame", "label", "plain", "good", "warm", "empty", "glitch", "cool",
                                            "shadow", "band", "menu", "cross")})
        STYLE.update({"edge": "1", "strong": "1", "logo": "1", "bad": "1", "dim": "2", "under": "2", "picked": "7",
                      "edge-bad": "1", "edge-warm": "1", "title": "1;7", "title-bad": "1;7", "title-warm": "1;7", "key": "7",
                      "pop": "7", "pop-strong": "1;7", "pop-frame": "7", "pop-off": "", "pop-on": "7", "wipe": "7",
                      # The panel reversed; the answer Enter takes bold and not reversed, and marked with ▸.
                      "dlg": "7", "dlg-strong": "1;7", "dlg-dim": "7", "dlg-field": "4;7", "dlg-value": "1;4;7",
                      "dlg-chip": "1", "dlg-on": "1", "dlg-off": "7"})
        STYLE[""] = ""


def heat(share):
    return "cool" if share < 0.3 else "good" if share < 0.6 else "warm" if share < 0.85 else "bad"


def spin(still):
    """A spinner's frame by the clock, so a key pressed does not turn it faster; `still` where nothing moves."""
    frames = GLYPH["spin"]
    return frames[int(time.time() * 8) % len(frames)] if MOTION[0] and frames else still


def frame(canvas, y, x, height, width, title, right="", tone=None):
    """A section: no box, but a grey band with the name as a chip and what is to be said of it at its right,
    the sides open, a + at the foot's corners. `tone` ("bad", "warm") colours the chip of a section that holds
    something wrong: the marks in it say what."""
    canvas.put(y, x, " " * width, "band")
    canvas.put(y, x + 1, f" {title} ", f"title-{tone}" if tone else "title")
    if right:
        canvas.put(y, x + width - 2 - len(right), right, "band")
    canvas.put(y + height - 1, x, "+", "frame")
    canvas.put(y + height - 1, x + width - 1, "+", "frame")


def meter(canvas, y, x, width, share, style=None, scan=False):
    """btop's meter: a row of segments, each coloured by where it sits, so how full it is
    reads as how hot. `scan`: a bright cell runs over the full part, for a job that is busy."""
    filled = round(max(0.0, min(1.0, share)) * width)
    at_scan = int(time.time() * 8) % (filled + 6) if scan and MOTION[0] and filled else -1
    for at in range(max(0, width)):
        if at < filled:
            canvas.put(y, x + at, GLYPH["full"], "strong" if at == at_scan else style or heat(at / max(width - 1, 1)))
        else:
            canvas.put(y, x + at, GLYPH["empty"], "empty")


def spark(canvas, y, x, width, history):
    """The history as a row of blocks, the newest at the right, each
    coloured by its height."""
    width = max(0, width)
    values = list(history)[-width:] if width else []
    canvas.put(y, x, "·" * (width - len(values)), "empty")
    for at, value in enumerate(values):
        level = min(len(BLOCKS) - 1, int(value / 100 * len(BLOCKS)))
        canvas.put(y, x + width - len(values) + at, BLOCKS[level], heat(value / 100))


# Braille's dots in a cell, from the foot up: the left column, then the right one.
DOTS = ((0x40, 0x04, 0x02, 0x01), (0x80, 0x20, 0x10, 0x08))


def graph(canvas, y, x, width, rows, history):
    """The history as an area of braille dots, `rows` high, two readings to a cell, the newest
    at the right, hotter colours higher up, as btop's. One row, or a font without braille:
    `spark`'s blocks, which have more steps in one row."""
    if rows <= 1 or not GLYPH["braille"]:
        spark(canvas, y + rows - 1, x, width, history)
        return
    width = max(0, width)
    values = list(history)[-2 * width:] if width else []
    values = [None] * (2 * width - len(values)) + values
    levels = rows * 4
    for row in range(rows):
        base = (rows - 1 - row) * 4
        style = heat(min(1.0, (base + 2) / levels))
        for cell in range(width):
            bits = 0
            for side in (0, 1):
                value = values[2 * cell + side]
                if value is None:
                    continue
                dots = round(max(0.0, min(100.0, value)) / 100 * levels)
                for dot in range(max(0, min(4, dots - base))):
                    bits |= DOTS[side][dot]
            if bits:
                canvas.put(y + row, x + cell, chr(0x2800 + bits), style)
            elif row == rows - 1:
                canvas.put(y + row, x + cell, "⣀", "empty")


def right(canvas, y, width, text, style):
    canvas.put(y, width - 2 - len(text), text, style)


# What moves, by the clock: when it began, and until when the screen is drawn quickly. Off where MOTION is.
ANIM = {"page": 0.0, "dialog": None, "dialog_at": 0.0, "view": None, "view_at": 0.0, "until": 0.0}


def ease(share):
    share = max(0.0, min(1.0, share))
    return 1 - (1 - share) ** 3


def progress(name, seconds):
    """How far an animation is, 0 to 1; always 1 where nothing moves."""
    return min(1.0, (time.time() - ANIM[name]) / seconds) if MOTION[0] else 1.0


def start(name, seconds):
    ANIM[name] = time.time()
    ANIM["until"] = max(ANIM["until"], time.time() + seconds)


def animating():
    return MOTION[0] and time.time() < ANIM["until"]


def decode(screen, share):
    """A page that is opened comes out of noise: below a line that runs down there is noise, on the line
    the text bright. The head and the foot stay."""
    if share >= 1 or not hasattr(screen, "rows"):
        return
    import random
    rng = random.Random(int(time.time() * 30))
    line = 2 + int(ease(share) * (screen.height - 3))
    for y in range(line, screen.height - 2):
        row = screen.rows[y]
        for x, (character, style) in enumerate(row):
            if character != " ":
                row[x] = (rng.choice(GLYPH["noise"]) if rng.random() < 0.6 else " ", "dim" if y > line else "strong")


class Inset:
    """The screen with a margin all round: a row at the top and the foot, two columns at the sides. What is
    drawn past its edge is cut, as on the screen itself."""

    def __init__(self, canvas, top=1, left=2, bottom=1, right=2):
        self.canvas, self.top, self.left = canvas, top, left
        self.height, self.width = canvas.height - top - bottom, canvas.width - left - right

    def put(self, y, x, text, style=""):
        if 0 <= y < self.height:
            if x < 0:
                text, x = text[-x:], 0
            self.canvas.put(y + self.top, x + self.left, text[:max(0, self.width - x)], style)

    def __getattr__(self, name):
        return getattr(self.canvas, name)


NAME = "RUNNERDECK"


def panel(canvas, title, share=1.0, wide=False):
    """The stage of a question: on the left a crosshair and the steps stacked down the side, over the right an
    orange panel that slides in (`share` of the way), the name down its edge on a black strip, the title as a
    black chip. Where its content goes: (x, width, bottom)."""
    width, height = canvas.width, canvas.height
    # A question of the setup has more to say than a yes or no: its panel is wider.
    size = min(width - 8, max(64, int(width * 0.62)) if wide else max(46, int(width * 0.44)))
    x0, bottom = width - size + int((1 - ease(share)) * size), height - 1
    cy, cx = bottom // 2, (width - size) // 2
    for row, (mark, clear) in enumerate((("╷", "     "), ("╶─┼─╴", "       "), ("╵", "     ")), start=-1):
        canvas.put(cy + row, cx - len(clear) // 2, clear, "")
        canvas.put(cy + row, cx - len(mark) // 2, mark, "cross")
    steps = "QUEUE ↓ RUN ↓ SHIP"
    for at, character in enumerate(steps if bottom > len(steps) + 2 else ""):
        canvas.put((bottom - len(steps)) // 2 + at, 0, "    ", "")
        canvas.put((bottom - len(steps)) // 2 + at, 2, character, "label")
    for row in range(bottom):
        canvas.put(row, x0, "   ", "dlg-chip")
        canvas.put(row, x0 + 3, " " * (size - 3), "dlg")
    gap = max(1, (bottom - 2) // len(NAME))
    for at, letter in enumerate(NAME if gap > 1 else ""):
        canvas.put(1 + at * gap, x0 + 1, letter, "dlg-on")
    canvas.put(1, x0 + 6, f" {title.upper().replace(' · ', '_').replace(' ', '_')} "[:size - 12], "dlg-chip")
    canvas.put(1, x0 + size - 5, GLYPH["lit"] * 3, "dlg-dim")
    return x0 + 6, size - 10, bottom


def popup(canvas, dialog):
    """A question as a login screen: the screen pushed back, the orange panel over the right, the question
    as a labelled field, the answers as two full-width buttons one over the other, the one Enter takes black
    and marked with ▸ (↑↓ and ←→ choose). For a token: the field, hidden but for how long it is."""
    import textwrap
    canvas.dim()
    if ANIM["dialog"] != id(dialog):
        ANIM["dialog"] = id(dialog)
        start("dialog_at", 0.35)
    x, w, bottom = panel(canvas, dialog["title"], progress("dialog_at", 0.3))
    lines = textwrap.wrap(dialog["words"], w - 2) or [""]
    field = "field" in dialog
    y = max(3, (bottom - (len(lines) + 7)) // 2)
    canvas.put(y, x, " TOKEN " if field else " QUESTION ", "dlg-chip")
    for at, line in enumerate(lines):
        canvas.put(y + 1 + at, x, " " * w, "dlg-field")
        canvas.put(y + 1 + at, x + 1, line, "dlg-field" if field else "dlg-value")
    y += 2 + len(lines)
    if field:
        canvas.put(y, x, " " * w, "dlg-field")
        canvas.put(y, x + 1, ("●" * len(dialog["field"]))[-(w - 3):] + "▏", "dlg-field")
        canvas.put(y + 2, x, "enter: set up · empty: ask gh · esc: cancel"[:w], "dlg-dim")
        return
    for at, (label, on) in enumerate(((dialog["yes"], dialog["focus"]), (dialog["no"], not dialog["focus"]))):
        canvas.put(y + at * 2, x, (("▸ " if on else "") + label.upper()).center(w), "dlg-on" if on else "dlg-off")
