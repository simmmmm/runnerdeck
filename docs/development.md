# Development

## Run the tests

```
python3 tests/test_runnerdeck.py
```

The tests need no network and no packages. They use stand-in `gh` and `ssh` programs.

`ci/test.yml` runs the tests on Linux, macOS, and Windows, with Python 3.9 and 3.13. GitHub does not let an assistant's token push to `.github/workflows/`. Move the file once (see `ci/README.md`).

## Make one file

```
python3 -m runnerdeck --build runnerdeck.pyz
python3 runnerdeck.pyz
```

`--install` makes `~/runnerdeck.pyz` and adds a `runnerdeck` command to your shell.

## Modules

| Module | Job |
|---|---|
| `runnerdeck/config.py` | Reads and checks the config file. Makes the `Config` object. |
| `runnerdeck/system.py` | Differences between macOS, Linux, and Windows. |
| `runnerdeck/runners.py` | The runners on this machine. |
| `runnerdeck/github.py` | Runs and requests, through `gh`. |
| `runnerdeck/machines.py` | CPU, GPU, memory, and temperature. |
| `runnerdeck/terminal.py` | Keys and drawing. |
| `runnerdeck/boxes.py` | The boxes of the screen. |
| `runnerdeck/intro.py` | The logo and the opening. |
| `runnerdeck/setup.py` | The questions of the first start. |
| `runnerdeck/app.py` | The loop and the commands. |

The `Config` object is passed to the functions that need it. There are no settings in module variables.

## What is tested

- The macOS and Linux parts: with recorded data and stand-in tools.
- The AMD and NVIDIA readings: with recorded data. Not on real cards.
- The Windows code: only in the CI run, and only the processes and the readings, not the screen. No person has run it.
