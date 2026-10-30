"""What differs between macOS, Linux and Windows: processes, notifications, the runner's download."""
import ctypes
import os
import platform
import shutil
import signal
import subprocess
import sys
import tempfile
import urllib.request
import zipfile


WINDOWS = os.name == "nt"


def exists(pid):
    """Whether a process with this pid runs. Not os.kill(pid, 0): on Windows
    that ends the process."""
    if WINDOWS:
        kernel = ctypes.windll.kernel32
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
        kernel.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel.OpenProcess(0x1000, 0, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        code = ctypes.c_uint32()
        got = kernel.GetExitCodeProcess(handle, ctypes.byref(code))
        kernel.CloseHandle(handle)
        return bool(got) and code.value == 259  # STILL_ACTIVE
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def apart():
    """Popen's arguments for a process that outlives this one, in a session
    of its own."""
    if WINDOWS:
        return {"creationflags": 0x08000000 | 0x00000200}  # CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP
    return {"start_new_session": True}


def alive(pidfile):
    """The process a pid file names, while it runs."""
    # ponytail: a pid the system has given to something else since reads as
    # alive; a check of the command line if that is ever seen.
    try:
        with open(pidfile) as file:
            pid = int(file.read().strip())
        return pid if exists(pid) else None
    except (OSError, ValueError):
        return None


def write(pidfile, pid):
    with open(pidfile, "w") as file:
        file.write(f"{pid}\n")


def end(pidfile):
    """The process and everything it started: it was a session's leader."""
    pid = alive(pidfile)
    if pid and WINDOWS:
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    elif pid:
        try:
            os.killpg(pid, signal.SIGTERM)
        except OSError:
            pass
    try:
        os.remove(pidfile)
    except OSError:
        pass


def notify(title, words, sound):
    def quoted(text):
        return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'

    if shutil.which("osascript"):
        command = ["osascript", "-e", f"display notification {quoted(words)} with title {quoted(title)} sound name {quoted(sound)}"]
    elif shutil.which("notify-send"):
        command = ["notify-send", "--", title, words]
    elif WINDOWS and shutil.which("powershell"):
        # The words go in the environment, not in the script: no quoting to get wrong.
        script = ("Add-Type -AssemblyName System.Windows.Forms, System.Drawing; "
                  "$n = New-Object System.Windows.Forms.NotifyIcon; $n.Icon = [System.Drawing.SystemIcons]::Information; "
                  "$n.Visible = $true; $n.ShowBalloonTip(5000, $env:RUNNER_TITLE, $env:RUNNER_WORDS, "
                  "[System.Windows.Forms.ToolTipIcon]::Info); Start-Sleep 6; $n.Dispose()")
        subprocess.Popen(["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", script],
                         env=dict(os.environ, RUNNER_TITLE=title, RUNNER_WORDS=words),
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **apart())
        return
    else:
        return
    subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def release(version):
    """The runner's download for this machine, GitHub's own names for them."""
    system = {"Darwin": "osx", "Linux": "linux", "Windows": "win"}.get(platform.system())
    arch = {"arm64": "arm64", "ARM64": "arm64", "aarch64": "arm64", "x86_64": "x64", "AMD64": "x64"}.get(platform.machine())
    if not system or not arch:
        raise OSError(f"no runner for {platform.system()} {platform.machine()}")
    pack = "zip" if system == "win" else "tar.gz"
    return f"https://github.com/actions/runner/releases/download/v{version}/actions-runner-{system}-{arch}-{version}.{pack}"


def download(url, folder):
    """The runner's files into a folder: curl and tar where there are, Python's
    own where there are not."""
    if WINDOWS:
        pack = os.path.join(tempfile.gettempdir(), "runner-download.zip")
        try:
            urllib.request.urlretrieve(url, pack)
            with zipfile.ZipFile(pack) as archive:
                archive.extractall(folder)
        except zipfile.BadZipFile:
            raise OSError(f"{url} is not a zip")
        finally:
            if os.path.exists(pack):
                os.remove(pack)
        return
    curl = subprocess.Popen(["curl", "-fsSL", url], stdout=subprocess.PIPE)
    subprocess.run(["tar", "xz", "-C", folder], stdin=curl.stdout, check=True)
    curl.stdout.close()
    if curl.wait():
        raise OSError(f"could not download {url}")


def own_command(*args):
    """The command and environment that run this program again with other
    arguments, from source or from a .pyz alike: the folder or archive the
    package is in goes on PYTHONPATH."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.pathsep.join(part for part in (root, os.environ.get("PYTHONPATH")) if part)
    return [sys.executable, "-m", "runner", *args], dict(os.environ, PYTHONPATH=path)
