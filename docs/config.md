# Config

The file is `~/.config/runnerdeck/config.ini`. Set `RUNNERDECK_CONFIG` to use another file.

Every file that the program writes has a list of all the options at its foot, as comments. Remove the `#` in front of a line to use it. Read the file with `cat`, or show it in your file manager: `open -R ~/.config/runnerdeck/config.ini` on macOS, `xdg-open ~/.config/runnerdeck` on Linux.

You do not have to write the file yourself. The program asks the questions the first time. `python3 -m runnerdeck --setup` asks them again, and keeps the old file as `config.ini.bak`. `python3 -m runnerdeck --init` writes an example file for you to edit.

The program checks the file when it reads it. A wrong value stops the start, with a message.

## Change it from the screen

Press `m` for the settings. In one list you can add a runner, add or take out a repository, choose the workflows that wait for your yes, add or remove a computer, and see where the file is. Each of these changes only its own part of the file. The rest stays as it is, comments too. The old file is kept as `config.ini.bak`, and a change that makes the file wrong is not kept. The keys `n`, `w` and `h` go to the first, third and fourth item directly.

## Sections

| Section | Use |
|---|---|
| `[deck]` | The repositories. Required. `computer = linux` is optional: it is what this computer is called on the screen, in place of its network name (up to 12 characters). |
| `[local]` | The runners on this machine. Leave it out if you only want to watch. |
| `[host NAME]` | Another machine. One section for each machine. |
| `[approval]` | Workflows that start only after you say yes. |
| `[health]` | The health box and its word in the head. Off without it. See [Health](health.md). |
| `[names]` | Short names for jobs in the notifications. |

## Examples

### 1. Watch one repository

You have no runners on this machine. You only want to see the runs.

```ini
[deck]
repos = owner/name
```

### 2. Keep three runners on this machine

The program sets up the runners that are missing. It starts the runners that are stopped. If `gh` cannot make a token, the program asks you to paste one.

```ini
[deck]
repos = owner/name

[local]
name = box
dir = ~/actions-runner
count = 3
```

The runners are `box`, `box-2`, and `box-3`. Their folders are `~/actions-runner`, `~/actions-runner-2`, and `~/actions-runner-3`.

Other options in `[local]`:

| Option | Meaning |
|---|---|
| `version` | The first runner version to download. Each runner updates itself. |
| `repo` | The repository for new runners. The default is the first in `[deck]`. |
| `keychain` | macOS. The program unlocks this keychain before it starts the runners. |
| `service` | Linux. A runner that runs as a systemd user service (for example `actions-runner.service`). It shows on the screen. It is not started or stopped from here. With this line and no `count`, no runner is started from here. |

A runner that you add with `n` is not in the config file. The program finds it by its folder.

## Runners that are set up already

There is no standard folder for a runner. The first start looks for the file `.runner` that a runner writes when it is registered. It looks in `~/actions-runner*` and a few levels down in your home folder. It does not look in `Documents`, `Desktop`, `Downloads`, or `Library`, because macOS asks you for permission to look there.

The setup then offers what it found: the repository, the name, the folder, and how many. The runners must be called `name`, `name-2`, `name-3`, in the folders `folder`, `folder-2`, `folder-3`. A runner in another place is shown, but the program cannot manage it. The program never downloads or registers a runner that is set up already.

### 3. Show a second machine

The second machine is a Linux PC. You reach it with SSH. Its runner is a systemd user service.

```ini
[host pc]
ssh = me@my-pc
service = actions-runner.service
```

The program shows CPU, GPU, memory, temperature, and the state of the runner. It only reads. It changes nothing on the PC.

### 3b. Show a Mac as the second computer

You run runnerdeck on a Linux PC, and you want to see your Mac too: its load, its battery and heat, its runners and its builds.

```ini
[host mac]
ssh = me@macbook
kind = macos
name = mac
dir = ~/actions-runner
count = 3
```

`name`, `dir` and `count` say where the runners of that Mac are: `mac`, `mac-2` and `mac-3` in `~/actions-runner`, `~/actions-runner-2` and `~/actions-runner-3`. Leave them out to only watch the Mac itself. `service` is for Linux: do not use it here.

The Mac is sent a small Python program over SSH, and runs it with its own `python3`. The program only reads. It uses the same tools that runnerdeck uses on its own Mac (`top`, `vm_stat`, `ioreg`), and it reads the log files of the runners. Nothing is installed on the Mac. The runners are shown but not started or stopped: for that, open runnerdeck on the Mac itself (`ssh -t mac runnerdeck`).

Use an SSH key. The program never asks for a password. If the PC does not answer, `NEEDS_YOU` on the first page says so.

### 4. Watch two repositories

```ini
[deck]
repos = owner/app, owner/website
```

### 5. Give jobs a short name

```ini
[names]
build = Build
check = CI
```

## Reading another computer: the key

The program reads another computer with ssh, with a key and never a password. Once, from the computer that runs the program:

1. `ssh user@host`. Answer `yes` when it asks about the host, then `exit`.
2. If it asks for a password: you have no key on the other computer yet. Make one if you have none (`ssh-keygen -t ed25519`, Enter at every question), then `ssh-copy-id user@host`.
3. `ssh -o BatchMode=yes user@host echo ok` must say `ok` without asking anything.

When a computer does not answer, the head of the screen says why. `runnerdeck --probe user@host [linux|macos]` shows what it sent back, raw.

## Which machines the program can read

| Machine | How |
|---|---|
| The Mac that runs the program | With the tools of macOS. |
| A Mac over SSH | With a small Python program that the Mac is sent. It uses the same tools as the Mac itself. |
| A Linux machine, here or over SSH | With one short script. It reads `/proc` and `/sys`. AMD cards: from `/sys`. NVIDIA cards: with `nvidia-smi`. |
| The Windows machine that runs the program | With the counters of Windows. NVIDIA cards: with `nvidia-smi`. The program does not show the temperature of the processor. |

A machine over SSH is a Linux PC or a Mac. A Windows machine over SSH is not read.
