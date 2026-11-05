"""runnerdeck: self-hosted GitHub Actions runners, the machines they run on and
the runs they work on, on one btop-style screen in the terminal.

    runnerdeck             start the local runners that are not running, then the screen.
                       The first time, questions on the screen make the config first.
    runnerdeck --setup     ask the questions again (the old config is kept as config.ini.bak)
    runnerdeck --init      write an example config file, to edit by hand
    runnerdeck --status    the screen once, as text; starts nothing
    runnerdeck --no-intro  start without the opening (or set RUNNERDECK_NO_INTRO=1; any key skips it too)
    runnerdeck --update   bring this clone up to date (a fast-forward of main; the runners are not touched)
    runnerdeck --probe USER@HOST [linux|macos]   what a computer sends back, raw (for an empty box)
    runnerdeck run [--name N] -- COMMAND   run a command as it is, and keep a record of it for the screen
    runnerdeck --install   copy this to ~/runnerdeck.pyz, and `runnerdeck` in your shell
    runnerdeck --build F   make one file F (runnerdeck.pyz) of the package

What it shows: this machine (CPU, GPU, memory, power, heat; macOS or Linux),
other machines over ssh, the runners on this machine (what each is doing and how
far its job is), the last runs of your repositories, and the log of one runner.
↑ and ↓ go over the runs; c cancels one, r runs it again, o opens it. What
cannot be taken back asks first, in a box in the middle.

Add a repository, say what runners it has, and that is all: a config file
(~/.config/runnerdeck/config.ini, or RUNNERDECK_CONFIG), see --init.

    [deck]
    repos = owner/name, owner/other        # what `gh` reads runs from

    [local]                                # runners on this machine (optional)
    name = box                             # box, box-2, box-3
    dir = ~/actions-runner                 # ~/actions-runner, -2, -3
    count = 3
    version = 2.338.2                      # a new runner's first; each updates itself
    keychain = ~/Library/Keychains/login.keychain-db   # macOS: unlocked before they start

    [host pc]                              # another machine, read-only, over ssh
    ssh = user@host                        # key login: BatchMode, never a password
    service = actions-runner.service       # its runner, a systemd user service

    [approval]                             # workflows only a person may start
    workflows = Deploy                     # an issue "Deploy: <branch> <sha>" ...
    label = deploy-request                 # ... with this label stands on the screen as waiting

    [health]                               # optional: a box and a head word for the CI's health
    smoke = owner/name:Smoke               # see docs/health.md

Nothing here starts an approval workflow by itself: an issue only asks; a or
enter in the screen starts it, after a question, from that branch if it is
still at that commit, and closes the issue.

Local runners run apart from the screen, in sessions of their own, so leaving it
(q) or losing the SSH connection leaves them running; x stops them. A watcher
(--watch) beside them notifies for every job that ends (osascript, or
notify-send) and writes it to jobs.log in the first runner's folder.

Python 3.9 and its standard library only. `python3 -m runnerdeck --build runnerdeck.pyz` makes one file of it:
copy that anywhere.
"""
