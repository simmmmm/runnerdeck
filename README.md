# runnerdeck

**One screen in your terminal for your GitHub Actions runners, your machines, and your workflow runs.**

```
 RUNNERDECK ▮▮▮  DECK_OVERVIEW    awake        1 DECK ▸   2 RUNS ▸   3 LOGS ▸   4 MACHINES ▸    16:38:27

 NEEDS_YOU   ■ CI red on main · app · 12 min · ↑↓ then l for its log

 BUSY          RED               RUNNERS    COMPUTER  STATE                                 1 of 2 busy
  ┓   ╱┏━┓      ┓               ● box       desk      ▰▰▰▰▰▱▱▱▱▱▱▱ step 3 of 5 · cargo build --r  4 min
  ┃  ╱ ┏━┛      ┃               ○ box-2     desk      Listening · last build succeeded           12 min
  ┻ ╱  ┗━━      ┻
                                 MACHINES      CPU              GPU    RAM                   HEAT/POWER
 WAITING       RUNS              desk          ····▃▄▅▅▆▅  62%   37%   ▰▰▰▰▰▰▰▱▱▱ 22/30 GB   71 °C
 ┏━┓           ┏━━
 ┃ ┃           ┗━┓
 ┗━┛           ━━┛


  RUNS                                                                 owner/app, owner/site · 8 s ago
  … Build        main     4f1c2a9 app  on box                                      in progress · 4 min
  ✗ CI           main     4f1c2a9 app                                                 failure · 12 min
  ✓ CI           main     4f1c2a9 app                                                 success · 31 min
  ✓ Deploy       main     4f1c2a9 site                                                success · 58 min
  ✓ CI           main     4f1c2a9 site                                            success · 1 h 15 min
+                                                                                                      +

 TOTAL  5 RUNS · 2 REPOSITORIES · 2 RUNNERS
 ↑↓ choose   m settings   s start   x stop   1-4 pages   q quit, runners stay on
```

*Example of the first page, drawn as text. The numbers are made up. On the terminal the screen is black, grey and orange, and the numbers are big; `--status` prints them in one row.*

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

The screen is black, off-white and grey, with one accent: orange. Orange is what is chosen, what is busy, and what asks for a look. Red means wrong. The colour is never the only sign: the numbers, the marks (✓ ✗ ▸ …), and the words are there too.

- The screen has four pages. Press `1` to `4`, or see the chips at the top right:
  - **1 DECK**: what needs you, every runner on every computer, each computer in one line, and the last runs. Four big numbers at the left: busy runners, red workflows, requests that wait, runs.
  - **2 RUNS**: the runs as a list. At the right, the chosen run: its result, what it is of, and its jobs and steps. The step that failed is red.
  - **3 LOGS**: the log of a runner, over the whole page. `←` `→` switch to another runner.
  - **4 MACHINES**: CPU and GPU as graphs, memory, heat, power, as high as the terminal lets them be.
- A section has its name on a chip in a grey band. A section that holds something wrong has a red chip.
- `NEEDS_YOU` on the first page says what asks for you: a red workflow, a computer that does not answer, a runner that is stopped. A request that waits for your yes has its own section, which never gives way.
- A question (leave, cancel, stop, a token) comes in as an orange panel at the right. The answer that Enter gives is black and has `▸`.
- The settings (`m`) are a list of bars. The setup's questions use the orange panel too.
- Things move: a page comes out of noise when you open it, the big numbers count up, a question slides in, the bars of the settings slide in, and an orange wipe goes over the screen when it starts and when it leaves. A busy runner, a run that goes on, and a build that runs have a spinner. The time in the head moves each second. Then you know that the screen is live.
- The runs say how old the list is (`8 s ago`). After two minutes without an answer it says `stale`. Before the first answer, it says that it asks GitHub.
- When you start the program, a short opening shows the sign and the name. It takes about one and a half seconds. Press any key to skip it. To turn it off, use `--no-intro` or set `RUNNERDECK_NO_INTRO=1`. `--status` has no opening.
- Nothing moves with `RUNNERDECK_CALM=1`: no opening, no animations, no spinners. The screen is then drawn one time each second. When something moves, it is drawn four times each second, and quickly while a page or a question comes in.
- A terminal with 8 colours (the Linux console, for example) gets 8 colours: yellow is the accent there. With `NO_COLOR` set, or in a terminal that says it has no colours, the screen uses bold, dim, underline and reverse only, and nothing moves.
- The Linux console and the old Windows console (not Windows Terminal) get simpler marks: `■` and `·` in the meters, `|/-\` as the spinner, `#` in the sign, no braille, and the big numbers in one row.
- The screen needs 80 columns. Under 100 columns the big numbers go, and the head shows only the numbers of the pages. The opening needs 48 columns and 15 rows. On a smaller terminal it does not show.
- `--status` prints the first page as text.

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
| `1` `2` `3` `4` | The pages: DECK, RUNS, LOGS, MACHINES. |
| `←` `→` or `Tab` | Switch to the log of another runner (page 3). All runners are tabs above the log. |
| `↑` `↓` | Choose a run, a request, or an issue. Only on the pages that show them: DECK (all three) and RUNS (runs). |
| `c` `r` `o` | Cancel, repeat, or open the chosen run. `o` opens a chosen issue of the health box too. |
| `←` `→` or `↑` `↓` in a question | Choose the answer. Enter gives it. |
| `←` `→`, `Home`, `End` in a text field | Move the cursor. What you type goes there. A list of repositories is not cleared when you type: what you type goes where the cursor is. |

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
