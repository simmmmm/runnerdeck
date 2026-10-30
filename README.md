# runner

**One screen in your terminal for your GitHub Actions runners, your machines, and your workflow runs.**

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

*Example screen. The numbers are made up.*

## What it does

- It shows each runner on your machine, what it does, and how far its job is.
- It shows CPU, GPU, memory, and temperature of your machines. It reads other machines over SSH.
- It shows the last workflow runs of your repositories. You can cancel, repeat, or open a run.
- You can add a new runner. You only paste the token.
- You can keep a workflow behind your approval.

## What you need

- Python 3.9 or newer. You do not need other packages.
- The [GitHub CLI](https://cli.github.com), logged in (`gh auth login`).
- macOS, Linux, or Windows.

## Start

1. Get the code: `git clone https://github.com/simmmmm/runner && cd runner`
2. Start the program: `python3 -m runner` (on Windows: `py -m runner`)
3. Answer the questions on the screen.

The first time, the program asks a few questions. It writes the config file for you. It can also make a `runner` command and set up the runners on this machine. When it is done, open a new terminal window and type `runner`.

To ask the questions again, use `--setup`. The config file is plain text. It lists all the options at its foot, as comments. Read it with `cat ~/.config/runner/config.ini`, or find it in your file manager. See also [Config](docs/config.md). To see the screen one time, as text, and start nothing, use `--status`.

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
| `q` | Leave. The runners keep running. |
| `n` | Add a new runner. |
| `w` | Choose again which workflows wait for your yes. |
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

- The program grew from a script that ran on a Mac. This version has only run with recorded data and stand-in tools.
- No person has run it on Windows. The Windows code is the least tested.
- There is no license yet.
