# Experimental quality protocol

Protocol 0.7 uses thirteen fixed tasks. It is a diagnostic suite, not a
quality score. A receipt is one model attempt on one task. It records the
requested and observed model, the complete request settings, task/suite
hashes, runtime image, elapsed time, tool calls, file diffs, independent
checks, and the reason the governor stopped the attempt.

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

Twelve tasks use the restricted typed-tool harness. Coding checks run in an
offline Docker container with a read-only root, resource limits, and no
Docker socket. That interface is a significant harness choice; its results
are not ordinary terminal-agent results. The document and refusal tasks
remain exploratory. The refusal check is a smoke test, not a cyber benchmark.

`arkade-add` is a native-agent task. A fresh, tagged Slicer VM runs OpenCode
against the entire pinned arkade checkout with its real `AGENTS.md` and a
short request to add shfmt. The agent can use its terminal, inspect upstream
releases, and run downloads. Its primary and small model are pinned to the
same contender. The VM is deleted after collection by default. Only after
the agent stops does the offline Docker judge run the full `pkg/get` package,
check a Go test in any changed test file, enforce gofmt and the README entry,
and inject independent release-URL checks. These include architecture aliases
and a second version tag. The old typed-tool arkade receipts remain historical
protocol 0.6 observations; they are not native-agent results.

OpenCode's provider configuration controls its sampling and response token
limits, so its receipt does not claim the typed-tool task's fixed sampling
settings. `--seconds` is shared; `--reasoning-effort` becomes an OpenCode
variant for this task. Do not compare the two harnesses as though identical.

Receipts are comparable only when suite hash, task hash, model/backend,
reasoning setting, limits, and harness match. Repeat tasks from fresh
workspaces. Preserve failures and timeouts rather than excluding them from a
report. Describe the checkpoint, quantisation, serving engine, and hardware
alongside public results, or link a RigMark bench receipt.
