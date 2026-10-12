# Releasing

Run the `check` workflow on `master` and ensure the control suite passes.
Then run `arkade rel` **without arguments** from a clean master checkout.
It creates the normal pre-release. The `release assets` workflow packages the
runnable Python CLI, tasks, and fixtures as a versioned tarball and uploads it
with a SHA-256 checksum. The upload event allows the existing release
promotion automation to publish the release as latest.

Check the release page for both assets and the workflow result. Do not add a
manual lightweight tag or call the GitHub release API instead of `arkade rel`.
