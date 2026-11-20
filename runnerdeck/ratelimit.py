"""GitHub's rate limit: 5000 requests an hour for a person, for all their computers and tools together. When it is used
up, everything that asks GitHub waits until it resets, and the screen says so, instead of asking again and again."""
import subprocess
import time

until = 0.0


def hit(stderr):
    """Whether `stderr` (what gh said) means that the limit is used up. Then asking stops until it resets. The
    reset time comes from `gh api rate_limit`, which GitHub does not count."""
    global until
    said = (stderr or "").lower()
    if "rate limit" not in said:
        return False
    reset = 0
    try:
        got = subprocess.run(["gh", "api", "rate_limit", "--jq", ".resources.core.reset"], capture_output=True,
                             text=True, timeout=15)
        reset = int(got.stdout.strip()) if got.returncode == 0 else 0
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    now = time.time()
    # Not told when: ten minutes, which is long enough for a secondary limit to pass.
    until = max(until, reset + 5 if reset > now else now + 600)
    return True


def wait():
    """Seconds still to wait; 0 when GitHub may be asked."""
    return max(0.0, until - time.time())


def words():
    when = time.strftime("%H:%M", time.localtime(until))
    return f"GitHub's limit of requests is used up. runnerdeck waits and asks again at {when}."
