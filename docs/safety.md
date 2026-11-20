# Safety

- Do not use a self-hosted runner on a public repository. A stranger can run code on your machine through a pull request.
- A job on a runner runs as your user. It can read your files.
- The program reads other machines with one short script. The script writes nothing. Characters that can change the screen are removed from the answer.
- The program checks the config file when it reads it. Text from an issue never reaches a command, except the workflow name, the branch name, and the commit.
- The program asks before it does a thing that you cannot undo.

## The registration token

When you add a runner, the token is on the command line of the `config` program for a few seconds. Other users of the same machine can see it. The token works one time and ends after one hour.

The screen shows the token as dots. The program does not save the token.

## GitHub's limit of requests

GitHub gives a person 5000 requests an hour, for all their computers and tools together. runnerdeck asks every 30 seconds while a run goes on or waits, and every 60 seconds when all is quiet; the health box is read every five minutes; a run that waits is asked about every 90 seconds. When GitHub says the limit is used up, everything stops asking until it resets, and the screen says at what time it asks again. See what is left: `gh api rate_limit --jq .resources.core`. Two computers that both run runnerdeck, with an agent that also polls, can use it up: keep the screen open on one of them.
