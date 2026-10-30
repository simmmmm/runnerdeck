"""The terminal: keys and size, how a frame is painted, and the pieces boxes are made of."""
import ctypes
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


# curses' own numbers for the keys the screen uses, so that Windows says the same.
ENTER = (10, 13, K_ENTER)


# The screen's colours by name, filled in by `colours` under curses; the
# text of --status has none, and draws an empty meter cell as a dot.
STYLE = {}


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

    def key(self):
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

    def key(self):
        """A key within a second, or -1; a changed size is a key too."""
        end = time.time() + 1
        while time.time() < end:
            if msvcrt.kbhit():
                character = msvcrt.getwch()
                if character in ("\x00", "\xe0"):
                    return {"H": K_UP, "P": K_DOWN, "K": K_LEFT, "M": K_RIGHT}.get(msvcrt.getwch(), 0)
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


def colours():
    """btop's way of looking: grey frames and labels, white for what matters,
    green to amber to red for how much; SGR's numbers, of 256 colours."""
    STYLE.update({
        "frame": "38;5;240",
        "label": "38;5;246",
        "plain": "38;5;252",
        "dim": "38;5;243",
        "strong": "1;38;5;255",
        "good": "38;5;114",
        "warm": "38;5;179",
        "bad": "1;38;5;167",
        "empty": "1;38;5;237",
        "picked": "7",
        # What a popup lies over, and the popup: a ground of its own.
        "under": "38;5;238",
        "pop": "38;5;252;48;5;236",
        "pop-strong": "1;38;5;255;48;5;236",
        "pop-frame": "38;5;250;48;5;236",
        "pop-off": "38;5;252;48;5;239",
        "pop-on": "1;38;5;234;48;5;255",
    })


def heat(share):
    return "good" if share < 0.6 else "warm" if share < 0.85 else "bad"


def frame(canvas, y, x, height, width, title, right=""):
    """A box with rounded corners, its title in the top edge, as btop's."""
    canvas.put(y, x, "╭─", "frame")
    canvas.put(y, x + 2, f" {title} ", "strong")
    start = x + 4 + len(title)
    end = x + width - 1 - (len(right) + 3 if right else 0)
    canvas.put(y, start, "─" * max(0, end - start), "frame")
    if right:
        canvas.put(y, end, f" {right} ", "label")
        canvas.put(y, x + width - 2, "─", "frame")
    canvas.put(y, x + width - 1, "╮", "frame")
    for row in range(y + 1, y + height - 1):
        canvas.put(row, x, "│", "frame")
        canvas.put(row, x + width - 1, "│", "frame")
    canvas.put(y + height - 1, x, "╰" + "─" * max(0, width - 2) + "╯", "frame")


def meter(canvas, y, x, width, share, style=None):
    """btop's meter: a row of blocks, each coloured by where it sits, so
    how full it is reads as how hot."""
    filled = round(max(0.0, min(1.0, share)) * width)
    for at in range(max(0, width)):
        if at < filled:
            canvas.put(y, x + at, "█", style or heat(at / max(width - 1, 1)))
        else:
            canvas.put(y, x + at, "█" if STYLE else "·", "empty")


def spark(canvas, y, x, width, history):
    """The history as a row of blocks, the newest at the right, each
    coloured by its height."""
    width = max(0, width)
    values = list(history)[-width:] if width else []
    canvas.put(y, x, "▁" * (width - len(values)), "empty")
    for at, value in enumerate(values):
        level = min(len(BLOCKS) - 1, int(value / 100 * len(BLOCKS)))
        canvas.put(y, x + width - len(values) + at, BLOCKS[level], heat(value / 100))


def right(canvas, y, width, text, style):
    canvas.put(y, width - 2 - len(text), text, style)


def popup(canvas, dialog):
    """btop's way of asking: the screen pushed back, and a box of its own over
    it with its two answers; n, the safe one, is where it starts."""
    words = dialog["words"]
    width = min(max(len(words) + 8, 44), canvas.width - 2)
    height = 8
    x, y = (canvas.width - width) // 2, max(0, (canvas.height - height) // 2)
    canvas.dim()
    for row in range(y, y + height):
        canvas.put(row, x, " " * width, "pop")
    title = f" {dialog['title']} "
    canvas.put(y, x, "╭─", "pop-frame")
    canvas.put(y, x + 2, title, "pop-strong")
    canvas.put(y, x + 2 + len(title), "─" * max(0, width - 3 - len(title)) + "╮", "pop-frame")
    for row in range(y + 1, y + height - 1):
        canvas.put(row, x, "│", "pop-frame")
        canvas.put(row, x + width - 1, "│", "pop-frame")
    canvas.put(y + height - 1, x, "╰" + "─" * max(0, width - 2) + "╯", "pop-frame")
    canvas.put(y + 2, x + (width - len(words)) // 2, words[:width - 4], "pop-strong")
    if "field" in dialog:
        # What is typed or pasted, hidden but for how long it is.
        shown = ("●" * len(dialog["field"]))[-(width - 8):]
        canvas.put(y + 4, x + 3, "› " + shown + "▏", "pop")
        canvas.put(y + 6, x + 3, "enter: set up · empty: ask gh · esc: cancel"[:width - 6], "pop-frame")
        return
    # Which one Enter takes, in the words too and not only in the colour.
    yes = f" ▸ {dialog['yes']} " if dialog["focus"] else f"   {dialog['yes']} "
    no = f"   {dialog['no']} " if dialog["focus"] else f" ▸ {dialog['no']} "
    start = x + (width - len(yes) - len(no) - 2) // 2
    canvas.put(y + 5, start, yes, "pop-on" if dialog["focus"] else "pop-off")
    canvas.put(y + 5, start + len(yes) + 2, no, "pop-off" if dialog["focus"] else "pop-on")
