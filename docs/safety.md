# Safety

- Do not use a self-hosted runner on a public repository. A stranger can run code on your machine through a pull request.
- A job on a runner runs as your user. It can read your files.
- The program reads other machines with one short script. The script writes nothing. Characters that can change the screen are removed from the answer.
- The program checks the config file when it reads it. Text from an issue never reaches a command, except the workflow name, the branch name, and the commit.
- The program asks before it does a thing that you cannot undo.

## The registration token

When you add a runner, the token is on the command line of the `config` program for a few seconds. Other users of the same machine can see it. The token works one time and ends after one hour.

The screen shows the token as dots. The program does not save the token.
