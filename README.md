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

One file, Python 3.9 and its standard library only. Needs [`gh`](https://cli.github.com)
for the runs, and ssh keys for other machines (never a password prompt).

## Use

```
python3 runner.py --init       # writes ~/.config/runner/config.ini
$EDITOR ~/.config/runner/config.ini
python3 runner.py              # starts local runners that are down, then the screen
python3 runner.py --status     # the screen once, as text
python3 runner.py --install    # copies itself to ~/runner.py and adds `runner`
```

q leaves, the runners keep running. x stops them, s starts them.

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
  only the Mac you run it on.

## Not done yet

- Not run against real GPU hardware: the amdgpu and k10temp files are read as the
  kernel documents them, tested with recorded output. NVIDIA is not read.
- Not tried on a real runner journal on Linux, or on Python 3.9 itself (syntax is
  checked for 3.9, tests ran on a newer Python).
- No licence is chosen yet.

It began as `dev/runners.py` in a private app repository, for one Mac and one PC.

## Tests

```
python3 tests/test_runner.py
```
