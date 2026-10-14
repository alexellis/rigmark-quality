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
- `selftest` checks both graders without calling a model. `run` calls a model;
  omit `--task` for all 13 tasks. `arkade-add` uses a disposable Docker
  OpenCode container by default, or Slicer with `--agent-runner slicer`;
  the other tasks use typed tools. `report` renders receipts.
- Build the offline judge image and native agent image, and run the
  reference/broken controls for changes to tasks, tools, or judges. Use the
  pinned arkade revision in `README.md` for `arkade-add`. Keep its agent prompt
  short, allow normal repository access,
  and inject independent checks only after it stops. Run Python compilation
  and governor unit tests as CI does.
- Run `actionlint` after workflow edits. Format only files you change, and use
  British English.
- Do not commit, push, or release unless explicitly asked. Sign off any
  authorised commit with `git commit -s`; release with `arkade rel` only when
  explicitly authorised.
