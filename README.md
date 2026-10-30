# runnerdeck

**One screen in your terminal for your GitHub Actions runners, your machines, and your workflow runs.**

```
 ◐ runnerdeck                                                                    awake
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

*Example screen. The numbers are made up.*

## What it does

- It shows each runner on your machine, what it does, and how far its job is.
- It shows CPU, GPU, memory, and temperature of your machines. It reads a second computer over SSH.
- It shows the last workflow runs of your repositories. You can cancel, repeat, or open a run.
- The first time, it asks a few questions on the screen and writes the config file for you. It finds runners that are set up already.
- You can add a new runner. You only paste the token.
- You can keep a workflow behind your approval, and change which ones later. Approval is a request that you answer on the screen. It does not lock the workflow: see [Approval](docs/approval.md).

## What you need

- Python 3.9 or newer. You do not need other packages.
- The [GitHub CLI](https://cli.github.com), logged in (`gh auth login`).
- macOS, Linux, or Windows.
- An SSH key for a second computer. It must run Linux for now. The program never asks for a password.

## Start

1. Get the code: `git clone https://github.com/simmmmm/runnerdeck && cd runnerdeck`
2. Start the program: `python3 -m runnerdeck` (on Windows: `py -m runnerdeck`)
3. Answer the questions on the screen.

The first time, the program asks a few questions. It writes the config file for you. It can also make a `runnerdeck` command and set up the runners on this machine. When it is done, open a new terminal window and type `runnerdeck`.

To ask the questions again, use `--setup`. The config file is plain text. It lists all the options at its foot, as comments. Read it with `cat ~/.config/runnerdeck/config.ini`, or find it in your file manager. See also [Config](docs/config.md). To see the screen one time, as text, and start nothing, use `--status`.

## Example

Three runners on this machine, and a second machine over SSH:

```ini
[deck]
repos = owner/name

[local]
name = box
dir = ~/actions-runner
count = 3

[host pc]
ssh = me@my-pc
service = actions-runner.service
```

## Keys

| Key | Action |
|---|---|
| `q` or `Esc` | Leave. It asks first. Press `q` again to say yes. The runners keep running. |
| `m` | Settings: add a runner, change the repositories, the workflows that wait for your yes, or the computers. |
| `n` | Add a new runner (also in the settings). |
| `w` | Choose again which workflows wait for your yes (also in the settings). |
| `h` | Add a computer to watch over SSH (also in the settings). |
| `s` / `x` | Start / stop the runners. |
| `Tab` | Show the log of the next runner. |
| `↑` `↓` | Choose a run. |
| `c` `r` `o` | Cancel, repeat, or open the chosen run. |

## More

- [Config: all options, with examples](docs/config.md)
- [Approval: keep a workflow behind your yes](docs/approval.md)
- [Safety](docs/safety.md)
- [Development: modules, tests, one-file build](docs/development.md)

## Status

- A person has run the screen, the setup, the runs and the approval on a Mac.
- The readings of a Linux PC (the GPU, the temperatures, the runner service) have only run with recorded data and stand-in tools. So has the SSH connection to a second computer.
- No person has run it on Windows. The Windows code is the least tested.
- The license is [MIT](LICENSE).
