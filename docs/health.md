# Health

The health box tells you at a glance if your CI is well. It is off. It starts when the config has a `[health]` section.

## Config

```ini
[health]
repos = simmmmm/Numa, simmmmm/Numa-dev, simmmmm/Numa-mac, simmmmm/Numa-home
disk = /mnt/data-games
disk_min = 20
smoke = simmmmm/Numa:Smoke
smoke_days = 8
queued_min = 30
label = ci-red
```

| Option | Meaning | Default |
|---|---|---|
| `repos` | The repositories to check. | The repositories of `[deck]`. |
| `disk` | More folders whose free space is shown. The runner folder (or your home folder) is always shown. | none |
| `disk_min` | A disk with less free space than this (GiB) is red. | 20 |
| `smoke` | A weekly workflow: `owner/name:Workflow`. A comma separates more than one. | none |
| `smoke_days` | The Smoke is stale after this many days without a good run. | 8 |
| `queued_min` | A run that is queued for longer than this (minutes) is shown. | 30 |
| `label` | The open issues with this label are listed. | `ci-red` |

Nothing else from the file reaches `gh`: a wrong value stops the start, with a message.

## What it shows

**The head.** One word, after the name: `all good`, or `N red`, `N stale`, `low disk`. `N red` counts the workflows whose last finished run on the default branch failed. `N stale` counts the Smoke workflows that are too old and the runs that are queued too long. If `gh` does not answer and nothing is known, it says `health: no answer`.

**The box.** One line for each repository. Each workflow is on it, red first:

| Mark | Meaning |
|---|---|
| `✓ CI` | The last finished run on the default branch is good. |
| `✗ Build 3 h` | It failed. It has been red for 3 hours: the time since the first failed run of the line of failures. |
| `… CI red 3 h` | A run is going now. The last finished run was red, so it stays red until it is good. |
| `flaky 2` | Two commits have a failed run and a later good run of the same workflow. |

Cancelled and skipped runs say nothing. They do not make a workflow green or red.

Then, in the box:

- **Disk**: the free space of the runner folder and of each `disk` folder. Red under `disk_min`. A folder that cannot be read shows `—`.
- **Smoke**: the age of the last good run, on any branch. It says `stale` after `smoke_days`, and `never green` when there is none.
- **Queued**: runs that wait longer than `queued_min`. A push waits when the PC with the runner is off.
- **The issues** with the label, the newest first, four at most.

If the screen is too short, the box is left out. The word in the head stays.

## Keys

`↑` and `↓` go over the requests, the issues, and the runs. `o` opens the chosen issue (or run) in the browser.

## How it asks GitHub

Every two minutes, in a thread of its own. For each repository: its default branch (once), the last 30 runs of that branch, the queued runs, and the open issues with the label. For each `smoke` line: the last good run of that workflow. That is about four calls for each repository. A repository that does not answer keeps what was known of it, and the head says so.

A flaky commit is only seen in the last 30 runs of the default branch. A run that is repeated with `r` replaces the first run on GitHub's list, so it does not show as flaky. Only a second run of the same commit does.

## Example: Numa

The workflow that watches the CI opens issues like `CI red: Build main a0d3a70` with the label `ci-red`. They show in the box, and `o` opens one. `--status` shows the box one time, as text.
