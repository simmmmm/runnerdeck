"""Time, and text from elsewhere."""
import calendar
import time


STAMP = "%Y-%m-%dT%H:%M:%SZ"


def moment(text, form):
    try:
        return calendar.timegm(time.strptime(text.strip(), form))
    except ValueError:
        return None


def ago(at):
    if at is None:
        return ""
    minutes = max(0, int(time.time() - at) // 60)
    if minutes < 1:
        return "now"
    if minutes < 60:
        return f"{minutes} min"
    return f"{minutes // 60} h {minutes % 60} min"


def clean(text):
    """Only what can be printed: a line from another machine must not move the
    cursor or colour the screen on this one."""
    return "".join(character for character in text if character.isprintable())


def read(path):
    try:
        with open(path) as file:
            return file.read()
    except OSError:
        return ""
