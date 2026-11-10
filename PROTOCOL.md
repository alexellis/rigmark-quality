# Experimental quality protocol

Protocol 1.0 uses nineteen fixed tasks. It is a diagnostic suite, not a
quality score. A receipt is one model attempt on one task. It records the
requested and observed model, the complete request settings, task/suite
hashes, runtime image, elapsed time, tool calls, file diffs, independent
checks, and the reason the governor stopped the attempt. Published example
JSON summaries omit tool calls, conversation content, and file diffs; their
cards describe only fields those summaries contain.

The default limit is 1,800 seconds per task. Typed-tool tasks request 32,768
output tokens per response and have no default model-turn cap; an explicit
`--max-steps N` can add one. OpenCode controls response tokens and turns for
the native arkade task. Reasoning mode should be selected explicitly for
matched runs. Provider-supplied usage and observed model names may be absent.
A model mismatch or transport failure is an invalid comparison, not a failed
coding task. Budget stops are recorded separately from independent checks.

The governor gives one recorded reminder after repeated unchanged reads,
searches, or green tests. A fourth identical unchanged read or search stops
as no progress; repeated green tests only produce a reminder. Repository
exploration receives a reminder after 25 turns without an edit, but has no
separate turn deadline. After the attempt stops, the judge reruns the public
tests against the final files and runs checks withheld from the agent. These
checks are public and may enter
training data. It reports file artefact correctness separately from whether
the conversation reached a final answer.
A task can have correct code and an unfinished conversation.

Eighteen tasks use the restricted typed-tool harness. Coding checks run in an
offline Docker container with a read-only root, resource limits, and no
Docker socket. That interface is a significant harness choice; its results
are not ordinary terminal-agent results. The document and refusal tasks
remain exploratory. The refusal check is a smoke test, not a cyber benchmark.
The agent's `run_tests` works on a disposable copy, so test-time writes cannot
alter protected workspace files. Withheld Go, C, and SQLite checks are
compiled before their source is removed from the execution copy; the parent
also requires terminal test evidence. These measures detect premature exits
and accidental fixture tampering. They are not a hardened defence against
code deliberately written to reverse engineer and forge the judge.

Two SQLite tasks extend that harness. `sqlite-migration` checks preservation
of all invoice lines, safe reruns, rollback on metadata conflicts, and
preservation of caller-owned transactions. `sqlite-report` checks exact
results on fresh data and whether SQLite uses explicit indexes for filtered
orders and joined lines. The latter is a query-design diagnostic, not a
cross-machine timing benchmark.

Four harder diagnostics extend the harness. `go-shutdown-deadlock` grades a
forced shutdown interleaving and preserves accepted work. The paired
`go-concurrency-review` asks for a concrete finding in one dispatcher and no
finding in its safe twin; its text-based causal-evidence check is a review
calibration aid, not an executable proof. `go-export-boundary` checks that a
cross-account request fails while legitimate owners retain access.
`c-frame-bounds` checks malformed inputs with AddressSanitizer and UBSan.
For the three Go/C and two SQLite repair tasks, the candidate's own regression
test must pass with its fix and fail when the original broken source is
restored. A compile or import error on the restored source does not count as a
reproducer.
The review task remains experimental until its calibration is supported by
multiple independent model runs.
The review receipt records plain versus fenced JSON separately from the
substantive finding, so a formatting slip does not erase a correct diagnosis.

`arkade-add` is a native-agent task. By default, a disposable Docker container
runs OpenCode against the entire pinned arkade checkout with its real
`AGENTS.md` and a short request to add shfmt. An optional fresh, tagged Slicer
VM can run the same task. The agent can use its terminal, inspect upstream
releases, and run downloads. Its primary and small model are pinned to the
same contender. The Docker runner copies only that provider's OpenCode settings
and credentials into a temporary home; the agent cannot mount the host home or
Docker socket. Both runners use a fresh checkout and remove it after the run
by default. Only after the agent stops does the offline Docker judge run the
full `pkg/get` package, check a Go test in any changed test file, enforce
gofmt and the README entry,
and inject independent release-URL checks. These include architecture aliases
and a second version tag. The old typed-tool arkade receipts remain historical
protocol 0.6 observations; they are not native-agent results.

OpenCode's provider configuration controls its sampling and response token
limits, so its receipt does not claim the typed-tool task's fixed sampling
settings. `--seconds` is shared; `--reasoning-effort` becomes an OpenCode
variant for this task. The Docker receipt preserves the event log and marks an
incomplete OpenCode session export as partial; model IDs are checked against
the available session and message headers. Do not compare the two harnesses
as though identical.

Receipts are comparable only when suite hash, task hash, model/backend,
reasoning setting, limits, and harness match. Docker and Slicer native-agent
receipts identify their distinct harnesses. Repeat tasks from fresh
workspaces. Preserve failures and timeouts rather than excluding them from a
report. Describe the checkpoint, quantisation, serving engine, and hardware
alongside public results, or link a RigMark bench receipt.
