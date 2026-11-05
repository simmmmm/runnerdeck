# runnerdeck

**One screen in your terminal for your GitHub Actions runners, your machines, and your workflow runs.**

```
 ◐ runnerdeck ▓▒░                                           update ready · u   awake   16:38:27
╭─ desk ──────────────────────────────────────────────────────── here · load 4.8 · 16 threads ─╮
│ CPU  ▅▄▄▄▄▅▄▄▄▄▃▄▃▄▅▅▅▅▅▅▆▆▇▇▆▅▅▅▆▇▆▅   62 %   Heat     CPU 71 °C   GPU 58 °C                │
│ GPU  ▄▄▄▄▃▃▃▂▂▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁   37 %   VRAM     8.2 / 16 GB                          │
│ RAM  ▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▱▱▱▱▱▱  22.2 / 30 GB     Busy     cargo 48 %   WorldOfWarship 6 %      │
╰─────────┴─────────┴─────────┴─────────┴─────────┴─────────┴─────────┴─────────┴─────────┴────╯
╭─ runners ────────────────────────────────────────────────────────────────────── 1 of 2 busy ─╮
│ ⠋ box    Running build                                                                 4 min │
│          ▰▰▰▰▰▰▰▰▱▱▱▱▱▱▱▱  step 3 of 5 · cargo build --release                   ~5 min left │
│ ○ box-2  Listening · last build succeeded                                             12 min │
╰─────────┴─────────┴─────────┴─────────┴─────────┴─────────┴─────────┴─────────┴─────────┴────╯
```

*Example screen. The numbers are made up.*

## What it does

- It shows each runner on your machine, what it does, and how far its job is.
- It shows CPU, GPU, memory, and temperature of your machines. It reads a second computer over SSH, a Linux PC or a Mac.
- It shows the last workflow runs of your repositories. You can cancel, repeat, or open a run.
- It can tell you if your CI is well: what is red and for how long, what is flaky, the free disk, and the issues that ask for a look. See [Health](docs/health.md).
- The first time, it asks a few questions on the screen and writes the config file for you. It finds runners that are set up already.
- It shows builds that are not on GitHub too, when you start them with `runnerdeck run -- <command>`. For a Rust project it says which compiler was used. See [Builds](docs/builds.md).
- You can add a new runner. You only paste the token.
- You can describe other kinds of request as data (a title pattern, a workflow, its inputs), and update the program with `runnerdeck --update`. See [Approval](docs/approval.md).
- You can keep a workflow behind your approval, and change which ones later. Approval is a request that you answer on the screen. It does not lock the workflow: see [Approval](docs/approval.md).

## What you need

- Python 3.9 or newer. You do not need other packages.
- The [GitHub CLI](https://cli.github.com), logged in (`gh auth login`).
- macOS, Linux, or Windows.
- An SSH key for a second computer: a Linux PC or a Mac. The program never asks for a password.

## Start

1. Get the code: `git clone https://github.com/simmmmm/runnerdeck && cd runnerdeck`
2. Start the program: `python3 -m runnerdeck` (on Windows: `py -m runnerdeck`)
3. Answer the questions on the screen.

The first time, the program asks a few questions. It writes the config file for you. It can also make a `runnerdeck` command and set up the runners on this machine. When it is done, open a new terminal window and type `runnerdeck`.

To ask the questions again, use `--setup`. The config file is plain text. It lists all the options at its foot, as comments. Read it with `cat ~/.config/runnerdeck/config.ini`, or find it in your file manager. See also [Config](docs/config.md). To see the screen one time, as text, and start nothing, use `--status`.

## The look

The screen is neon green and cyan on a dark ground. Amber means warm. Red means wrong. The colour is never the only sign: the numbers, the marks (✓ ✗ …), and the words are there too.

- Each box has its name on a ground of its own. A box that holds something wrong (a failed run, a runner whose last job failed) has red corners and a red name.
- The keys at the foot are on a ground of their own, so you can find them quickly.
- A busy runner, a run that goes on, and a build that runs have a spinner. A light runs over the meter of a busy job. The time in the head moves each second. Then you know that the screen is live.
- The github box says how old the list is (`8 s ago`). After two minutes without an answer it says `stale`. Before the first answer, it says that it asks GitHub.
- When the terminal has many rows, the CPU and GPU graphs are two rows high, in braille dots. The screen never takes these rows from the runs or the log.
- When you start the program, a short opening shows the logo. It takes about one second. Press any key to skip it. To turn it off, use `--no-intro` or set `RUNNERDECK_NO_INTRO=1`. `--status` has no opening.
- Nothing moves with `RUNNERDECK_CALM=1`: no opening, no spinners. The screen is then drawn one time each second. When something moves, it is drawn four times each second.
- A terminal with 8 colours (the Linux console, for example) gets 8 colours. With `NO_COLOR` set, or in a terminal that says it has no colours, the screen uses bold, dim, and reverse only, and nothing moves.
- The Linux console and the old Windows console (not Windows Terminal) get simpler marks: `■` and `·` in the meters, `|/-\` as the spinner, and no braille.
- The screen needs 80 columns. The opening needs 44 columns and 11 rows. On a smaller terminal it does not show.

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
| `←` `→` or `Tab` | Switch to the log of another runner. All runners are tabs above the log. |
| `↑` `↓` | Choose a run. |
| `c` `r` `o` | Cancel, repeat, or open the chosen run. `o` opens a chosen issue of the health box too. |

## More

- [Config: all options, with examples](docs/config.md)
- [Builds that are not on GitHub](docs/builds.md)
- [Approval: keep a workflow behind your yes](docs/approval.md)
- [Health: red workflows, flaky runs, disk, stale Smoke](docs/health.md)
- [Safety](docs/safety.md)
- [Development: modules, tests, one-file build](docs/development.md)

## Status

- A person has run the screen, the setup, the runs and the approval on a Mac.
- The readings of a Linux PC (the GPU, the temperatures, the runner service) have only run with recorded data and stand-in tools. So has the SSH connection to a second computer.
- No person has run it on Windows. The Windows code is the least tested.
- The license is [MIT](LICENSE).
