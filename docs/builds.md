# Builds that are not on GitHub

A build or a test run that you start yourself does not show in GitHub's list of runs. To see it on the screen, start it with `runnerdeck run`:

```
runnerdeck run --name tests -- cargo test --workspace
runnerdeck run -- dev/check.sh
```

The command runs as it is: with the same input, the same output and the same exit code. The program writes down when it began, how it ended, and how long it took. Where the command does not print to a terminal (a script or an assistant started it), what it prints is kept too.

## On the screen

A box `builds` shows the latest five, as the runners are shown:

- `…` is a build that runs now, with how long it has run.
- `✓` or `✗` is how a build ended, with how long it took and how long ago.
- `–` is a build that was stopped (Ctrl-C) or that stopped without an end.

The page RUNS lists the builds of this computer among GitHub's runs, with `here` as their repository. Choose one with `↑` `↓`: the right side shows its command, its folder, and the last lines it printed. They follow the build while it runs.

A build that you start at a terminal prints there, with its colours and its progress bar, and no log is kept of it.

If the computer with the builds is another one that you watch over SSH, its builds show in a box with its name (`builds · pc`).

## Which Rust toolchain

For a Rust folder (a `Cargo.toml`, or a `rust-toolchain` file, in it or above it), the record says which compiler was used, like `rustc 1.82.0 stable`. It shows after the commit in the `builds` box, where the line has room.

This matters when a project does not pin its toolchain: every machine then uses its own default, and two machines can build with different compilers without anybody seeing it. The record shows it.

The program follows the rules of rustup, in their order: `+toolchain` on a `cargo` command, `RUSTUP_TOOLCHAIN`, an override that was set for the folder, a `rust-toolchain` or `rust-toolchain.toml` file, and last the default.

It reads these from the files of rustup and does not ask rustup. A folder can name a toolchain that is not installed, and rustup would then download it. A log must install nothing. A toolchain that is named and not there is written as `1.99.0 (not installed)`. Without rustup, the `rustc` of the PATH is used, if there is one.

The program notes the toolchain when the build starts. It does not see a script that changes toolchain while it runs.

Another language can be added: a function in `DETECTORS` in `runnerdeck/builds.py` takes the folder and the command, and gives a short text, or nothing.

## Names

`--name` is the name on the screen. Without it, the program takes the command and the word after it, like `cargo test`. The branch and the commit of the folder you are in are written down too.

## Where the records are

One small file for each build, in `~/.local/share/runnerdeck/builds/`, and a `.log` file beside it with what the build printed. Set `RUNNERDECK_DATA` to use another folder. The latest 60 are kept. While a build runs, its file is touched every 20 seconds. A build that has not been touched for 90 seconds and has no end was interrupted, and is shown with `–`.

## For a build that an assistant runs

Put this in the instructions of the repository (for instance `CLAUDE.md`), so that the builds and the tests that it runs are written down:

```
Run builds and tests with `runnerdeck run --name <short name> -- <command>` when `runnerdeck`
is installed (for instance: `runnerdeck run --name tests -- cargo test --workspace`).
```

## What it does not see

Only what is started with `runnerdeck run`. A build that you start from an app (Xcode) or without the prefix is not written down.
