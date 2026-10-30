# Approval

Use approval for a workflow that you must start yourself. A deploy is a good example.

```ini
[approval]
workflows = Deploy
label = deploy-request
```

The setup asks `gh` for the workflows of your repositories and lets you choose from the list. Move with the arrow keys, choose with the space bar, and press Enter. If `gh` gives no list, you write the names.

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
