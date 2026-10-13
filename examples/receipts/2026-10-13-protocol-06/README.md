# Complete protocol 0.6 runs from 13 October 2026

[ASCII cards](cards.txt) and the 26 JSON files in this directory record one
complete, unselected 13-task attempt per model. These are public summaries;
conversation content, tool calls, file diffs, and endpoint details remain in
the private source receipts. The suite used its restricted typed-tool harness,
not a full coding agent with shell access. The reports are task diagnostics,
not model or quantisation scores.

Both runs used suite SHA256
`930fcb80c9e536c177aaab182af8cd57e4978a6568b14b6c7450b897ea10f159`,
runtime image `sha256:086fd83ccb51eb829065ab6ba2642fa96dd6a2328a99a8f891d7ade821385188`,
and arkade fixture revision `e5215097ce8d9340af060412663f7c7130c594dd`.
Requests used temperature 0, top-p 1, seed 20261011, `reasoning_effort=low`,
provider-default thinking, a 32,768-token response cap, no turn cap, and a
1,800-second deadline per task. Models were reached through Toilgate. The
observed GLM backend identified itself as `nvidia/GLM-5.3-Flash-NVFP4`; the
DeepSeek backend identified itself as `deepseek-v4-flash-0731`. No model
mismatch or transport failure occurred.

Each model finished every conversation. Independent artefact checks found:

- GLM-5.3-Flash: worker-pool cancellation failed because the output channel
  did not close after cancellation; arkade generated the amd64 asset for Linux
  arm64; statement redaction passed its public example but failed both hidden
  documents.
- DeepSeek V4 Flash 0731: arkade omitted the Linux amd64 architecture suffix;
  statement redaction failed the public example and both hidden documents.

The arkade submissions passed their own public package tests. The independent
URL check caught the architecture errors after each attempt ended. A single
attempt can vary even with the same requested settings; these receipts do not
establish a stable difference between models. Use the JSON files to inspect
each check, completion outcome, and request setting before drawing conclusions.
