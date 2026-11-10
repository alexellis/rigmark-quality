# Six-task protocol 1.0 pilot

The [ASCII cards](cards.txt) and eighteen JSON summaries record one attempt
per model on each of the six tasks added in protocol 1.0. This is a selected
pilot of the new tasks, **not** a complete nineteen-task suite run or a model
ranking. All three models passed the independent checks and finished the
conversation on all six tasks in this pilot.

| Task | GLM 5.3 Flash | DeepSeek V4.1 Flash 1017 | Qwen 3.8 27B FP8 |
| --- | --- | --- | --- |
| SQLite migration | Pass | Pass | Pass |
| SQLite report | Pass | Pass | Pass |
| Go shutdown deadlock | Pass | Pass | Pass |
| Go concurrency review | Pass | Pass | Pass |
| Go export boundary | Pass | Pass | Pass |
| C frame bounds | Pass | Pass | Pass |

All receipts use suite SHA-256
`f2409820d9f11a35b5c1fd258c295218d0fa0420ecf2e1f19a6d5bc969093aac`,
temperature 0, top-p 1, seed 20261011, requested low reasoning, provider
default thinking, a 32,768-token response cap, no turn cap, and a 1,800-second
task deadline. All six tasks were rerun for each model on 10 November after
the hidden acceptance and regression checks were strengthened. The controls
reject premature exits from the Go and C acceptance tests, a migration that
weakens target constraints or changes unrelated schema, one that rolls back
the caller's transaction or mutates unrelated data on rerun, a report with
incorrect output aliases or an exclusive date boundary, replaced baseline
tests, and comment-only SQLite regression tests. The shutdown judge exercises
concurrent submissions and closers, then checks that every accepted job was
processed. The report judge accepts a valid partial index, and the review
judge accepts equivalent descriptions of a channel-close race. Public tests
run on disposable copies. Withheld fixtures are compiled before their source
is removed from the execution copy, and terminal evidence is parsed from the
complete logs before presentation output is shortened.

GLM 5.3 Flash NVFP4 ran through Toilgate on four DGX Sparks. DeepSeek V4.1
Flash 1017 used Mia's 2.9 bpw EXL3 TensorFold recipe directly on two DGX
Sparks. Qwen 3.8 27B FP8 ran through Toilgate and vLLM on an RTX PRO 6000
Blackwell. These serving stacks and hardware differ, so elapsed times are
diagnostic observations, not a controlled speed comparison.

The public JSON files contain request settings, observed model identities,
checks, usage, and stop states. Conversation content, tool calls, file diffs,
and endpoint details remain in private source receipts. The public cards point
readers to the checks and stop state available in these summaries. One pass
per model does not establish reliability; this pilot did not separate the
three systems on correctness.
