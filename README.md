# runnerdeck

**Your GitHub Actions runners, machines and runs on one terminal screen.**

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

## What it does

- Every runner, on every computer: what it runs and how far it is.
- CPU, GPU, memory and heat, here and on a second computer over SSH.
- The last runs of your repositories. Cancel, repeat or open one. A run that goes on this computer shows what it prints, live, on RUNS.
- What is red, what is flaky, what waits for your yes. See [Health](docs/health.md) and [Approval](docs/approval.md).
- A new runner: you paste the token.
- Builds outside GitHub: `runnerdeck run -- <command>`. See [Builds](docs/builds.md).

## Start

Python 3.9+ and the [GitHub CLI](https://cli.github.com), logged in. Nothing else.

```bash
git clone https://github.com/simmmmm/runnerdeck && cd runnerdeck
python3 -m runnerdeck
```

Answer the questions. It writes the config and the `runnerdeck` command. Update with `runnerdeck --update`.

## Keys

| Key | Action |
|---|---|
| `1` – `4` | DECK, RUNS, LOGS, MACHINES |
| `↑` `↓` | Choose a run, request or issue |
| `c` `r` `o` | Cancel, repeat, open |
| `←` `→` | Other log (LOGS) |
| `s` / `x` | Start / stop the runners |
| `m` | Settings |
| `n` `w` `h` | New runner, approvals, computer |
| `q` | Leave. The runners keep running. |

## Options

- `--status`: the first page as text. Starts nothing.
- `--setup`: the questions again.
- `--no-intro`, `RUNNERDECK_CALM=1`, `NO_COLOR`: no opening, no motion, no colour.

## More

[Config](docs/config.md) · [Builds](docs/builds.md) · [Approval](docs/approval.md) · [Health](docs/health.md) · [Safety](docs/safety.md) · [Development](docs/development.md)

Tested by hand on a Mac. Linux PC and SSH only with recorded data. Windows untested. [MIT](LICENSE).
