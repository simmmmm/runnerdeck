# Builds that are not on GitHub

A build or a test run that you start yourself does not show in GitHub's list of runs. To see it on the screen, start it with `runnerdeck run`:

```
runnerdeck run --name tests -- cargo test --workspace
runnerdeck run -- dev/check.sh
```

The command runs as it is: with the same input, the same output and the same exit code. The program only writes down when it began, how it ended, and how long it took.

## On the screen

A box `builds` shows the latest five, as the runners are shown:

- `…` is a build that runs now, with how long it has run.
- `✓` or `✗` is how a build ended, with how long it took and how long ago.
- `–` is a build that was stopped (Ctrl-C) or that stopped without an end.

If the computer with the builds is another one that you watch over SSH, its builds show in a box with its name (`builds · pc`).

## Names

`--name` is the name on the screen. Without it, the program takes the command and the word after it, like `cargo test`. The branch and the commit of the folder you are in are written down too.

## Where the records are

One small file for each build, in `~/.local/share/runnerdeck/builds/`. Set `RUNNERDECK_DATA` to use another folder. The latest 60 are kept. While a build runs, its file is touched every 20 seconds. A build that has not been touched for 90 seconds and has no end was interrupted, and is shown with `–`.

## For a build that an assistant runs

Put this in the instructions of the repository (for instance `CLAUDE.md`), so that the builds and the tests that it runs are written down:

```
Run builds and tests with `runnerdeck run --name <short name> -- <command>` when `runnerdeck`
is installed (for instance: `runnerdeck run --name tests -- cargo test --workspace`).
```

## What it does not see

Only what is started with `runnerdeck run`. A build that you start from an app (Xcode) or without the prefix is not written down.
