# Waiting to be moved

The test workflow, which runs the tests on Linux, macOS and Windows (3.9 and
3.13). It is here and not in `.github/workflows/` because an assistant's token
may not push there. Move it once:

    git mv ci/test.yml .github/workflows/test.yml && git rm ci/README.md
    git commit -m "Test workflow" && git push
