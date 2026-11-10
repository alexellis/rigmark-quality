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
`5da4b9af79e46f55983d6b6c7955c7963187892eb1c9a6ef91c7cf747737fdee`,
temperature 0, top-p 1, seed 20261011, requested low reasoning, provider
default thinking, a 32,768-token response cap, no turn cap, and a 1,800-second
task deadline. The four Go/C tasks for GLM and DeepSeek were first run on
9 November; their SQLite tasks and all six Qwen tasks ran on 10 November.

GLM 5.3 Flash NVFP4 ran through Toilgate on four DGX Sparks. DeepSeek V4.1
Flash 1017 used Mia's 2.9 bpw EXL3 TensorFold recipe directly on two DGX
Sparks. Qwen 3.8 27B FP8 ran through Toilgate and vLLM on an RTX PRO 6000
Blackwell. These serving stacks and hardware differ, so elapsed times are
diagnostic observations, not a controlled speed comparison.

The public JSON files contain request settings, observed model identities,
checks, usage, and stop states. Conversation content, tool calls, file diffs,
and endpoint details remain in private source receipts. The card's generic
instruction to read JSON for tool calls therefore applies to full local
receipts, not these public summaries. One pass per model does not establish
reliability; this pilot did not separate the three systems on correctness.
