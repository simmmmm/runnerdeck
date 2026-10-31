# Approval

Use approval for a workflow that you must start yourself. A deploy is a good example.

```ini
[approval]
workflows = Deploy
label = deploy-request
```

The setup asks `gh` for the workflows of your repositories and lets you choose from the list. Move with the arrow keys, choose with the space bar, and press Enter. If `gh` gives no list, you write the names.

## What approval is, and what it is not

Approval here is a request that you answer on the screen. The program starts the workflow when you say yes. It does not stop the workflow from starting by its own triggers, such as a push. It is an agreement, not a lock.

For a real block, use the environments of GitHub with required reviewers. GitHub then holds the job until a reviewer approves it. Some plans offer this only for public repositories, so check yours. You can use both: GitHub blocks, and runnerdeck shows the request on your screen.

## Change it later

Press `w` on the main screen. The list of workflows opens again, and the ones that wait for your yes are already chosen. Change them with the space bar and press Enter. The program changes only the `[approval]` section of the file. The rest stays as it is, comments too. The old file is kept as `config.ini.bak`. If you choose none, the section is taken out.

## How it works

1. A person or a tool opens an issue. The issue has the label from the config file.
2. The title of the issue is `Deploy: <branch> <commit>`. For example: `Deploy: main a0d3a70`.
3. The issue shows on the screen as "waiting for you".
4. You press `a` to start the workflow. You press `d` to decline.
5. The program closes the issue.

## When the program starts the workflow

The program starts the workflow only in these cases:

- You say yes in the box.
- The branch is still at the commit in the title.
- No run of this commit is on its way.

An issue can only ask. It cannot start a workflow.

The program takes only three things from the title: the name of the workflow, the name of the branch, and the commit. The workflow must be in the list in the config file.

## Other kinds of request: `[request NAME]`

`[approval]` knows one shape of title: `Deploy: <branch> <commit>`. For a workflow that takes inputs, or a title of another shape, add a section for it. There can be any number. This is data: no change in the program is needed.

```ini
[request publish]
label = publish-request
workflow = Publish
title = Publish: {mode} {version} {sha}
mode = linux|apple|home
version = version
sha = sha
ref = main
input sha = {sha}
input mode = {mode}
```

An issue with the label `publish-request` and the title `Publish: linux 0.48.0 a0d3a70` waits on the screen. When you say yes, the program runs:

```
gh workflow run Publish --repo owner/name --ref main -f sha=a0d3a70 -f mode=linux
```

What an issue can say stays small:

- The workflow, the branch (`ref`) and the names of the inputs come from the config file, never from the issue.
- Each `{field}` of the title is one of: `sha`, `version`, `branch`, or a list of plain words (`linux|apple|home`). No other pattern is possible, so a title cannot carry more than a word, a version, a branch or a commit.
- The title must match as a whole. Anything extra makes it no request at all.
- Each input is a field of the title or a plain word.
- As with `[approval]`: when there is a `ref` and a `sha`, the branch must still be at that commit, and a run of that commit that is on its way is not started again.
- An issue can only ask. You say yes.

A section that is wrong makes the config invalid, and the program says which line.

## Update the program

`runnerdeck --update` (or *Update runnerdeck* in the settings) brings the clone it was installed from up to date, and makes the installed command `runnerdeck` from it again (`--install` remembers which clone). It only fast-forwards `main`. It does nothing when the clone is on another branch, has changes of your own, or has commits of its own. The runners are other programs and keep running. Start runnerdeck again to use the new version.

## Why did a run fail?

Choose the run and press `l`: the end of what its failed steps wrote opens on the screen, as GitHub keeps it. `o` opens the run in the browser.
