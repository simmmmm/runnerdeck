# runner

**One screen in your terminal for your GitHub Actions runners, your machines, and your workflow runs.**

`runner` shows what your self-hosted runners do. It shows how busy your machines are. It shows the last runs of your repositories. You can start, stop, and add runners from the same screen.

```
 ◐ runner                                                                    awake
╭─ desk ───────────────────────────────────────────────────── here · load 1.4 · 16 threads ─╮
│ CPU  ▁▁▂▂▃▃▅▅▆▇██▇▆▅▃▂▂▁▁▁▂▃▅▇██▇▅▃▂▁    74 %   Heat     CPU 71 °C  GPU 58 °C        │
│ GPU  ▁▁▁▁▁▁▂▂▃▃▃▃▃▂▂▁▁▁▁▁▁▁▁▂▃▃▃▃▂▂▁▁▁    37 %   Card     142 W  VRAM 4.0 / 16 GB      │
│ RAM  ██████████████···········   17.2 / 32 GB                                          │
╰────────────────────────────────────────────────────────────────────────────────────────╯
╭─ runners ─────────────────────────────────────────────────────────────── 1 of 2 busy ─╮
│ ● box    Running build                                                         4 min   │
│ ○ box-2  Listening · last build succeeded                                      12 min  │
╰────────────────────────────────────────────────────────────────────────────────────────╯
```

*Example screen. The numbers are made up for this example.*

## What it does

- It shows each runner on your machine. You see what the runner does and how far its job is.
- It shows CPU, GPU, memory, and temperature of your machines.
- It reads other machines over SSH. Nothing is installed on them.
- It shows the last workflow runs of one or more repositories.
- You can cancel a run, run it again, or open it in the browser.
- You can add a new runner. You only paste the token.
- You can keep some workflows behind your approval (see "Approval").

## What you need

- Python 3.9 or newer. You do not need other packages.
- The [GitHub CLI](https://cli.github.com) (`gh`). Log in with `gh auth login`.
- macOS, Linux, or Windows.
- An SSH key for each other machine. The program never asks for a password.

## Install

Use the program from the source folder:

```
git clone https://github.com/simmmmm/runner
cd runner
python3 -m runner --help
```

You can also make one file. Copy this file to any place:

```
python3 -m runner --build runner.pyz
python3 runner.pyz
```

To put a `runner` command in your shell, do this:

```
python3 -m runner --install
```

## Start

1. Make the config file: `python3 -m runner --init`
2. Open the file `~/.config/runner/config.ini`. Change the repository name.
3. Start the program: `python3 -m runner`

To see the screen one time as text, use `--status`.

## Examples

Put each example in the config file.

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

### 3. Show a second machine

The second machine is a Linux PC. You reach it with SSH. The runner on the PC is a systemd user service.

```ini
[host pc]
ssh = me@my-pc
service = actions-runner.service
```

The program shows CPU, GPU, memory, temperature, and the state of the runner. It only reads. It does not change anything on the PC.

### 4. Watch two repositories

```ini
[deck]
repos = owner/app, owner/website
```

### 5. Approval

Some workflows must start only after you say yes. Put their names in the config file:

```ini
[approval]
workflows = Deploy
label = deploy-request
```

## Keys

| Key | Action |
|---|---|
| `q` | Leave the screen. The runners keep running. |
| `s` | Start the runners that are stopped. |
| `x` | Stop all runners. |
| `n` | Add a new runner. |
| `Tab` | Show the log of the next runner. |
| `↑` `↓` | Choose a run or a request. |
| `c` | Cancel the chosen run. |
| `r` | Run the chosen run again. |
| `o` | Open the chosen run in the browser. |
| `a` or `Enter` | Start the chosen request. |
| `d` | Decline the chosen request. |

The program asks you before it does a thing that you cannot undo. Press `y` to say yes. Press `n` to say no.

## Add a new runner

1. Press `n`.
2. Open this page on GitHub: Settings › Actions › Runners › New self-hosted runner.
3. Copy the token. Paste it in the box on the screen.
4. Press `Enter`.

The program downloads the runner and registers it. It gives the runner the next name, for example `box-4`. Then it starts the runner.

If you leave the box empty, the program asks `gh` for a token. This works only if you are an admin of the repository.

The screen shows the token as dots. The program does not save the token.

## Approval

Use approval for a workflow that you must start yourself. A deploy is a good example.

1. A person or a tool opens an issue. The issue has the label from the config file.
2. The title of the issue is `Deploy: <branch> <commit>`. For example: `Deploy: main a0d3a70`.
3. The issue shows on the screen as "waiting for you".
4. You press `a` to start the workflow. You press `d` to decline.
5. The program closes the issue.

The program starts the workflow only in these cases:

- You say yes in the box.
- The branch is still at the commit in the title.
- No run of this commit is on its way.

An issue can only ask. It cannot start a workflow.

## Safety

- Do not use a self-hosted runner on a public repository. A stranger can run code on your machine through a pull request.
- A job on a runner runs as your user. It can read your files.
- The program reads other machines with one short script. The script writes nothing. Characters that can change the screen are removed from the answer.
- The program checks the config file when it reads it. A wrong value stops the start.

## Status

- The program grew from a script that ran on a Mac. This new version is tested with recorded data and stand-in tools.
- No person has run this version on a real Mac, on a real Linux PC with a GPU, or on Windows.
- **The Windows code is the least tested.** It was written from the documentation. The tests in `ci/test.yml` try it on `windows-latest`. To use them, move the file to `.github/workflows/` (see `ci/README.md`).
- The GPU readings are tested with recorded data. AMD cards are read from `/sys`. NVIDIA cards are read with `nvidia-smi`. A person has not tested them on real cards.
- A Mac is read with the tools of macOS. This works only on the Mac that runs the program. Other machines over SSH must run Linux.
- There is no license yet.

## Tests

```
python3 tests/test_runner.py
```

## Project layout

| Module | Job |
|---|---|
| `runner/config.py` | Reads and checks the config file |
| `runner/system.py` | Differences between macOS, Linux, and Windows |
| `runner/runners.py` | The runners on this machine |
| `runner/github.py` | Runs and requests, through `gh` |
| `runner/machines.py` | CPU, GPU, memory, and temperature |
| `runner/terminal.py` | Keys and drawing |
| `runner/boxes.py` | The boxes of the screen |
| `runner/app.py` | The loop and the commands |
