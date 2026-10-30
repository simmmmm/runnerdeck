# runner

Your self-hosted GitHub Actions runners, the machines they run on and the runs
they work on, on one btop-style screen in the terminal.

- **Machines:** this one (CPU, GPU, memory, power, heat; macOS or Linux) and
  others over ssh (Linux: CPU, GPU, VRAM, card power, CPU and GPU temperature).
- **Runners:** what each is doing and how far its job is, by the steps GitHub
  counts and the time the last good run of that workflow took; the log of one.
- **Runs:** the last runs of every repository you list. Cancel, run again, open.
- **Approval:** workflows only a person may start. An issue asks for one; you
  start it from the screen, after a question, or decline it.

A small package (`runner/`, one module for each part), Python 3.9 and its standard library only, on
macOS, Linux and Windows. `--build` makes one file of it, `runner.pyz`, to copy anywhere. Needs [`gh`](https://cli.github.com)
for the runs, and ssh keys for other machines (never a password prompt).

## Use

```
python3 -m runner --init       # writes ~/.config/runner/config.ini
$EDITOR ~/.config/runner/config.ini
python3 -m runner              # starts local runners that are down, then the screen
python3 -m runner --status     # the screen once, as text
python3 -m runner --build runner.pyz   # one file of it, to copy anywhere: python3 runner.pyz
python3 -m runner --install    # builds ~/runner.pyz and adds `runner` to your shell
```

q leaves, the runners keep running. x stops them, s starts them.

**n makes a new runner.** Paste the registration token (Settings › Actions ›
Runners › New self-hosted runner) and press enter; leave it empty and `gh` asks
for one, if you are admin of the repository. The runner is downloaded, registered
as the next `name-N` and started. The token is shown only as dots and is not stored.

## Config

Add a repository, say what runners it has, and that is it:

```ini
[deck]
repos = owner/name, owner/other

[local]                                # runners on this machine: ~/actions-runner, -2, -3
name = box
dir = ~/actions-runner
count = 3
version = 2.338.2
# keychain = ~/Library/Keychains/login.keychain-db   # macOS, unlocked before they start

[host pc]                              # another machine, read-only
ssh = user@host
service = actions-runner.service       # its runner, a systemd user service

[approval]
workflows = Deploy                     # an issue "Deploy: <branch> <sha>" with this label
label = deploy-request                 # waits on the screen; a starts it, d declines it
```

The keys are the ones you have: `gh auth login` for GitHub (a registration token
for a new local runner comes from it, or is asked for), and your ssh key for a
host. runner stores no secret.

## What it will and will not do

- Everything a screen can start asks first (a box, `y` or `n`), and a request
  starts only the workflow named in `[approval]`, from the branch it names, if
  that branch is still at the commit it names.
- Other machines are only read: one `sh -s` over a kept ssh connection, a script
  on stdin that reads `/proc` and `/sys`, writes nothing and installs nothing. What
  comes back is parsed as numbers and names, and anything unprintable is dropped
  before it is drawn.
- Config values that reach `gh`, ssh or a file name are checked when it is read.
- A remote host is Linux. The box for a Mac is read with the Mac's own tools, so
  only the Mac you run it on, and a Windows machine likewise (the system's own
  times and memory, and an NVIDIA card through `nvidia-smi`; no processor heat).

## Not done yet

- Not run against real GPU hardware: the amdgpu and k10temp files are read as the
  kernel documents them, and `nvidia-smi` as its documentation says, tested with
  recorded output and stand-in tools.
- **Windows has never been run by a person.** What is Windows' own (keys from
  `msvcrt`, the console's escape sequences, processes, the readings, notifications
  through PowerShell, `config.cmd`) was written from the documentation and is tried
  by `ci/test.yml` (to move to `.github/workflows/`, see `ci/README.md`) on `windows-latest`, which tests the processes
  and the readings, not the screen. A person with a Windows machine should open
  it once.
- Not tried on a real runner journal on Linux, or on Python 3.9 itself (syntax is
  checked for 3.9, tests ran on a newer Python).
- No licence is chosen yet.

It began as `dev/runners.py` in a private app repository, for one Mac and one PC.

## Tests

```
python3 tests/test_runner.py
```
