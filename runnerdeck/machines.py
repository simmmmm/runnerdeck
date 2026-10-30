"""What a machine is doing: a Mac through its own tools, a Linux machine (here or over ssh) through one script, Windows through the system's counters."""
import ctypes
import os
import platform
import re
import shutil
import subprocess
import threading
import time
from collections import deque
from .util import clean, read
from .system import WINDOWS
from .config import HOST, load
from .runners import said_by


def run(*command):
    return subprocess.run(command, capture_output=True, text=True, timeout=10).stdout


def cpu():
    """All cores' busy share over the last second: top's second sample, its
    first being since the Mac started."""
    idle = re.findall(r"CPU usage:.*?([\d.]+)% idle", run("top", "-l", "2", "-n", "0", "-s", "1"))
    return 100 - float(idle[-1]) if idle else None


def gpu():
    found = re.search(r'"Device Utilization %"=(\d+)', run("ioreg", "-r", "-d", "1", "-w", "0", "-c", "IOAccelerator"))
    return int(found.group(1)) if found else None


def memory():
    """Used and all of it, in GB: active, wired and compressed pages, near
    what Activity Monitor calls Memory Used."""
    said = run("vm_stat")
    page = int(re.search(r"page size of (\d+) bytes", said).group(1))

    def pages(name):
        found = re.search(rf"{name}:\s+(\d+)", said)
        return int(found.group(1)) if found else 0

    used = (pages("Pages active") + pages("Pages wired down") + pages("Pages occupied by compressor")) * page
    return used / 2**30, int(run("sysctl", "-n", "hw.memsize")) / 2**30


def watts(load):
    """`SystemLoad` in watts. On battery it is negative, and ioreg prints it
    as the unsigned 64 bits: "18446744073709520 W", on battery."""
    if not load:
        return None
    return abs(load - (1 << 64) if load >= 1 << 63 else load) / 1000


def power():
    """The battery's own telemetry: what the whole Mac draws (`SystemLoad`,
    milliwatts, Apple silicon laptops), how full it is, whether it is on
    power and charging, and its temperature (hundredths of a degree). None
    without a battery."""
    said = run("ioreg", "-r", "-w", "0", "-c", "AppleSmartBattery")
    if not said.strip():
        return None

    def number(key):
        found = re.search(rf'"{key}"\s*=\s*(-?\d+)', said)
        return int(found.group(1)) if found else None

    def yes(key):
        return re.search(rf'"{key}"\s*=\s*Yes', said) is not None

    load, warm = number("SystemLoad"), number("Temperature")
    # A share on Apple silicon (of a MaxCapacity of 100), milliampere-hours
    # on an Intel Mac: the ratio is the percentage either way.
    full, most = number("CurrentCapacity"), number("MaxCapacity")
    return {"watts": watts(load), "external": yes("ExternalConnected"),
            "charging": yes("IsCharging"), "percent": 100 * full / most if full is not None and most else None,
            "warm": warm / 100 if warm else None}


def thermal():
    """How hot macOS says the Mac is, as it throttles by it: NSProcessInfo's
    thermalState, through the Objective-C runtime. A sensor's degrees would
    want sudo (powermetrics)."""
    objc = ctypes.cdll.LoadLibrary("/usr/lib/libobjc.A.dylib")
    ctypes.cdll.LoadLibrary("/System/Library/Frameworks/Foundation.framework/Foundation")
    objc.objc_getClass.restype = objc.sel_registerName.restype = ctypes.c_void_p
    objc.objc_getClass.argtypes = objc.sel_registerName.argtypes = [ctypes.c_char_p]
    send = objc.objc_msgSend
    send.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    send.restype = ctypes.c_void_p
    info = send(objc.objc_getClass(b"NSProcessInfo"), objc.sel_registerName(b"processInfo"))
    send.restype = ctypes.c_long
    state = send(info, objc.sel_registerName(b"thermalState"))
    return ("Nominal", "Fair", "Serious", "Critical")[state] if 0 <= state < 4 else None


class Machine:
    """What the Mac is doing, every few seconds, so a glance says whether
    it is too much."""

    READINGS = (("cpu", cpu), ("gpu", gpu), ("memory", memory), ("power", power), ("thermal", thermal))

    def __init__(self, once=False):
        self.now = {}
        # The last few minutes of CPU and GPU, for their graphs.
        self.cpu, self.gpu = deque(maxlen=200), deque(maxlen=200)
        if once:
            self.sample()
        else:
            threading.Thread(target=self.loop, daemon=True).start()

    def sample(self):
        now = {}
        for name, read in self.READINGS:
            # A reading this Mac does not give (no battery, another macOS)
            # is left out rather than taking the screen down with it.
            try:
                now[name] = read()
            except Exception:
                now[name] = None
        for history, value in ((self.cpu, now["cpu"]), (self.gpu, now["gpu"])):
            if value is not None:
                history.append(value)
        self.now = now

    def loop(self):
        # top's own second of sampling, then two more: a graph that moves.
        while True:
            self.sample()
            time.sleep(2)


# What the PC is asked, as one script on its stdin: the kernel's own counters
# (/proc, and the amdgpu and k10temp files in /sys), nothing to install and
# nothing to write. cpu is read twice, a second apart. `log` is last: all that
# follows it is the runner's journal.
PC_ASKS = r"""
echo "stat $(head -n1 /proc/stat)"
sleep 1
echo "stat $(head -n1 /proc/stat)"
echo "load $(cut -d' ' -f1 /proc/loadavg)"
echo "threads $(nproc)"
sed -n 's/^\(MemTotal\|MemAvailable\): *\([0-9]*\).*/mem_\1 \2/p' /proc/meminfo
for d in /sys/class/drm/card[0-9]/device; do
    [ -r "$d/gpu_busy_percent" ] || continue
    echo "gpu $(cat "$d/gpu_busy_percent")"
    echo "vram_used $(cat "$d/mem_info_vram_used" 2>/dev/null)"
    echo "vram_total $(cat "$d/mem_info_vram_total" 2>/dev/null)"
    for h in "$d"/hwmon/hwmon*; do
        echo "gpu_temp $(cat "$h/temp1_input" 2>/dev/null)"
        echo "gpu_power $(cat "$h/power1_average" "$h/power1_input" 2>/dev/null | head -n1)"
    done
    break
done
if command -v nvidia-smi >/dev/null 2>&1; then
    echo "nvidia $(nvidia-smi --query-gpu=utilization.gpu,temperature.gpu,power.draw,memory.used,memory.total --format=csv,noheader,nounits 2>/dev/null | head -n1)"
fi
for h in /sys/class/hwmon/hwmon*; do
    [ "$(cat "$h/name" 2>/dev/null)" = k10temp ] && echo "cpu_temp $(cat "$h/temp1_input" 2>/dev/null)"
done
echo "runner $([ -n "$1" ] && systemctl --user is-active "$1" 2>/dev/null)"
echo log
[ -n "$1" ] && journalctl --user -u "$1" -n 200 --no-pager -o cat 2>/dev/null
exit 0
"""


def parse_nvidia(text):
    """nvidia-smi's one line (utilization %, degrees, watts, MiB used, MiB all)
    as the fields of a machine's answer; "[N/A]" and the like are left out."""
    fields = [word.strip() for word in text.split(",")]
    if len(fields) != 5:
        return {}

    def number(word, scale=1.0):
        try:
            return float(word) / scale
        except ValueError:
            return None

    got = {"gpu": number(fields[0]), "gpu_temp": number(fields[1]), "gpu_power": number(fields[2])}
    used, size = number(fields[3], 1024), number(fields[4], 1024)
    if used is not None and size:
        got["vram"] = (used, size)
    return {key: value for key, value in got.items() if value is not None}


def parse_pc(said):
    """A machine's answer as numbers and names. A key it did not give is left out,
    and so is a number that is not one."""
    head, _, log = said.partition("\nlog\n")
    got, stats = {}, []
    for line in head.splitlines():
        key, _, value = line.partition(" ")
        if key == "stat":
            stats.append(value.split()[1:])
        else:
            got[key] = value.strip()

    def number(key, scale=1.0):
        try:
            return float(got[key]) / scale
        except (KeyError, ValueError):
            return None

    now = {"threads": number("threads"), "load": number("load"), "gpu": number("gpu"),
           "cpu_temp": number("cpu_temp", 1000), "gpu_temp": number("gpu_temp", 1000),
           "gpu_power": number("gpu_power", 1e6), "runner": clean(got.get("runner", "")) or None}
    try:
        # user nice system idle iowait ...: busy is everything but idle and iowait.
        first, second = ([int(field) for field in stat] for stat in stats[:2])
        total = sum(second) - sum(first)
        idle = second[3] + second[4] - first[3] - first[4]
        now["cpu"] = 100 * (1 - idle / total) if total > 0 else None
    except (ValueError, IndexError):
        now["cpu"] = None
    total, free = number("mem_MemTotal", 2**20), number("mem_MemAvailable", 2**20)
    now["memory"] = (total - free, total) if total and free is not None else None
    used, size = number("vram_used", 2**30), number("vram_total", 2**30)
    now["vram"] = (used, size) if used is not None and size else None
    now["log"] = [clean(line) for line in log.splitlines()]
    # An AMD card's own files first; NVIDIA's tool for what they left empty.
    for key, value in parse_nvidia(got.get("nvidia", "")).items():
        if now.get(key) is None:
            now[key] = value
    return now


def windows_here():
    """This Windows machine in the shape of a machine's answer: the system's
    own times and memory through ctypes; an NVIDIA card through nvidia-smi.
    Heat and power of the processor are not given without a driver."""
    kernel = ctypes.windll.kernel32

    def times():
        idle, system, user = (ctypes.c_uint64() for _ in range(3))
        kernel.GetSystemTimes(ctypes.byref(idle), ctypes.byref(system), ctypes.byref(user))
        return idle.value, system.value, user.value

    first = times()
    time.sleep(1)
    second = times()
    # The kernel's time includes the idle time.
    total = (second[1] - first[1]) + (second[2] - first[2])
    busy = 100 * (1 - (second[0] - first[0]) / total) if total > 0 else None

    class Status(ctypes.Structure):
        _fields_ = [("length", ctypes.c_uint32), ("load", ctypes.c_uint32), ("total", ctypes.c_uint64),
                    ("free", ctypes.c_uint64), ("page_total", ctypes.c_uint64), ("page_free", ctypes.c_uint64),
                    ("virtual_total", ctypes.c_uint64), ("virtual_free", ctypes.c_uint64), ("extended", ctypes.c_uint64)]

    status = Status()
    status.length = ctypes.sizeof(Status)
    memory = None
    if kernel.GlobalMemoryStatusEx(ctypes.byref(status)):
        memory = ((status.total - status.free) / 2**30, status.total / 2**30)
    now = {"threads": float(os.cpu_count() or 0), "load": None, "gpu": None, "cpu_temp": None, "gpu_temp": None,
           "gpu_power": None, "runner": None, "cpu": busy, "memory": memory, "vram": None, "log": []}
    if shutil.which("nvidia-smi"):
        got = subprocess.run(["nvidia-smi", "--query-gpu=utilization.gpu,temperature.gpu,power.draw,memory.used,memory.total",
                              "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=10)
        now.update(parse_nvidia(got.stdout.splitlines()[0] if got.returncode == 0 and got.stdout.strip() else ""))
    return now


def ask_pc(host, service=""):
    """One round trip: the machine's answer, parsed, or None when it did not
    give one. Without a host it is this machine, asked with the same script."""
    # Checked again where it is used: a host that starts with a dash would be
    # an option to ssh.
    if (host is not None and not HOST.match(host)) or (service and not HOST.match(service)):
        return None
    if host is None and WINDOWS:
        return windows_here()
    command = ["sh", "-s", service]
    if host is not None:
        # Windows' ssh does not keep a connection open between calls.
        keep = [] if WINDOWS else ["-o", "ControlMaster=auto", "-o", "ControlPersist=120",
                                   "-o", "ControlPath=" + os.path.expanduser("~/.ssh/runnerdeck-%C")]
        command = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", *keep, "--", host, *command]
    got = subprocess.run(command, input=PC_ASKS, capture_output=True, text=True, timeout=20)
    return parse_pc(got.stdout) if got.returncode == 0 and got.stdout.strip() else None


class Pc:
    """A Linux machine, every few seconds: the same readings as the Mac's.
    Over ssh when it has a host, and here when it has none."""

    def __init__(self, name, host=None, service="", once=False):
        self.name, self.host, self.service = name, host, service
        self.now, self.at = {}, None
        # True once it has been asked and did not answer: the screen leaves its box out and says so in the head.
        self.failed = False
        self.cpu, self.gpu = deque(maxlen=200), deque(maxlen=200)
        if once:
            self.sample()
        else:
            threading.Thread(target=self.loop, daemon=True).start()

    def sample(self):
        try:
            now = ask_pc(self.host, self.service)
        except (OSError, subprocess.SubprocessError):
            now = None
        if now is None:
            # Kept as it was, but called stale: a machine that is off must
            # not look busy.
            self.at, self.failed = None, True
            return
        for history, value in ((self.cpu, now["cpu"]), (self.gpu, now["gpu"])):
            if value is not None:
                history.append(value)
        self.now, self.at, self.failed = now, time.time(), False

    def reachable(self):
        return self.at is not None

    def state(self):
        """The runner there, as a local one's: (state, job, since, last)."""
        if not self.reachable():
            return "unreachable", "", None, ""
        if self.now.get("runner") != "active":
            return "stopped", "", None, ""
        return said_by(self.now.get("log", []))

    def loop(self):
        while True:
            self.sample()
            time.sleep(2 if self.reachable() else 15)


def build_machines(cfg, once=False):
    """This machine's box and the others'. A Mac is read with its own tools; a
    Linux machine, here or over ssh, with the one script (PC_ASKS)."""
    here = Machine(once) if platform.system() == "Darwin" else None
    pcs = [Pc(platform.node().split(".")[0][:12] or "here", None, "", once)] if here is None else []
    return here, pcs + [Pc(host["name"], host["ssh"], host["service"], once) for host in cfg.hosts]
