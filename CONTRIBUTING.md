# Contributing tasks

Open an issue with a real failure mode, a small self-contained workspace, the
expected behaviour, and an independent check that can reject plausible but
wrong output. Separate task correctness from whether the agent finishes.
Please include a broken control and a reference solution. Keep all fixtures
synthetic or redistributable, and avoid tests that require a live third-party
service, secrets, or a large model download.

A new task changes the suite hash. Existing receipts remain valid historical
evidence for their own hash; do not mix them with new runs or an altered
harness. Document any changes to prompts, tools, limits, or scoring before
claiming a comparison.

Use British English and format only the files you change. Pull requests should
include the control result and an example receipt where possible.
