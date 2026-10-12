# Working on RigMark Quality

- Read `README.md`, `PROTOCOL.md`, and `CONTRIBUTING.md` before changing the
  runner or a task. This is an experimental diagnostic suite, not a model score.
- Keep tasks small, synthetic, offline, and independently judgeable. Give each
  task a broken control and a reference solution. Never expose withheld checks
  to the model during an attempt.
- Treat prompts, tools, limits, fixtures, and judges as protocol. A change to
  `quality_suite/` changes the suite hash; do not compare new receipts with old
  ones as though the harness were identical. Preserve failures and timeouts.
- Keep artefact correctness separate from conversation completion. Do not turn
  a correct file followed by a reasoning loop into an unqualified pass.
- `selftest` checks the harness without calling a model. `run` calls a model;
  omit `--task` for all 13 tasks. `report` renders receipts as ASCII or JSON.
- Build the offline image and run the reference/broken controls for changes to
  tasks, tools, or judges. Use the pinned arkade revision in `README.md` for
  `arkade-add`. Run Python compilation and governor unit tests as CI does.
- Run `actionlint` after workflow edits. Format only files you change, and use
  British English.
- Do not commit, push, or release unless explicitly asked. Sign off any
  authorised commit with `git commit -s`; release with `arkade rel` only when
  explicitly authorised.
