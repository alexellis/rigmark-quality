# Experimental quality protocol

Protocol 0.3 uses thirteen fixed tasks. It is a diagnostic suite, not a
quality score. A receipt is one model attempt on one task. It records the
requested and observed model, the complete request settings, task/suite
hashes, runtime image, elapsed time, tool calls, file diffs, independent
checks, and the reason the governor stopped the attempt.

The default limits are 32,768 output tokens per response and 1,800 seconds
per task. Wall-clock time is the primary run limit; there is no default
model-turn cap. An explicit `--max-steps N` can add one. Reasoning mode should
be selected explicitly for matched runs. Provider-supplied usage and observed
model names are recorded, but some providers omit them. A model mismatch or
transport failure is an invalid comparison, not a failed coding task. A
provider may reject or lower the requested response limit. Budget stops are
recorded separately from independent task checks.

The governor gives one recorded reminder after repeated unchanged reads,
searches, or green tests. A later repeat stops as no progress. The judge runs
checks withheld from the agent only after the attempt stops. These checks are
public and may enter training data. It reports file artefact
correctness separately from whether the conversation reached a final answer.
A task can have correct code and an unfinished conversation.

Coding tasks run in an offline Docker container with a read-only root,
resource limits, and no Docker socket. The model sees only the task workspace
and typed tools; it does not see acceptance tests during the run. This restricted
interface is a significant harness choice. It should not be treated as an
ordinary OpenCode or terminal-agent result. The document and refusal tasks
remain exploratory. The refusal check is a smoke test, not a cyber benchmark.

Receipts are comparable only when suite hash, task hash, model/backend,
reasoning setting, limits, and harness match. Repeat tasks from fresh
workspaces. Preserve failures and timeouts rather than excluding them from a
report. Describe the checkpoint, quantisation, serving engine, and hardware
alongside public results, or link a RigMark bench receipt.
