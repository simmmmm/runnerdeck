# Config

The file is `~/.config/runner/config.ini`. Set `RUNNER_CONFIG` to use another file.

Every file that the program writes has a list of all the options at its foot, as comments. Remove the `#` in front of a line to use it. Read the file with `cat`, or show it in your file manager: `open -R ~/.config/runner/config.ini` on macOS, `xdg-open ~/.config/runner` on Linux.

You do not have to write the file yourself. The program asks the questions the first time. `python3 -m runner --setup` asks them again, and keeps the old file as `config.ini.bak`. `python3 -m runner --init` writes an example file for you to edit.

The program checks the file when it reads it. A wrong value stops the start, with a message.

## Sections

| Section | Use |
|---|---|
| `[deck]` | The repositories. Required. |
| `[local]` | The runners on this machine. Leave it out if you only want to watch. |
| `[host NAME]` | Another machine. One section for each machine. |
| `[approval]` | Workflows that start only after you say yes. |
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

Use an SSH key. The program never asks for a password. If the PC does not answer, the box says so.

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

## Which machines the program can read

| Machine | How |
|---|---|
| The Mac that runs the program | With the tools of macOS. |
| A Linux machine, here or over SSH | With one short script. It reads `/proc` and `/sys`. AMD cards: from `/sys`. NVIDIA cards: with `nvidia-smi`. |
| The Windows machine that runs the program | With the counters of Windows. NVIDIA cards: with `nvidia-smi`. The program does not show the temperature of the processor. |

A machine over SSH must run Linux.
