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
