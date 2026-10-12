# RigMark Quality

![RigMark Quality: does it finish the job?](docs/images/rigmark-quality-hero.png)

**Small coding and tool tasks, run through a typed-tool harness.** RigMark
Quality asks a model to edit code, use tools, and finish the job. It checks the
resulting files independently and records what happened in a shareable receipt.
This is not a full shell-enabled coding-agent session.

This is **experimental**. Its thirteen tasks are a diagnostic starting point,
not a complete quality test of a model, a quantisation, or an agent product.
There is no overall ranking. The main [RigMark](https://github.com/alexellis/rigmark)
repository remains the serving benchmark for prose, code, prefill, and
concurrency; use `rigmark bench` there. This repository owns `rigmark quality`.

The suite is useful for people serving models on DGX Sparks and RTX systems at
home, and it also accepts compatible hosted endpoints. You can try an
[OpenCode Zen](https://docs.opencode.ai/docs/zen/) free model or an
[OpenRouter](https://openrouter.ai/docs/api/api-reference/chat/send-chat-completion-request)
free model, then compare *task receipts* under the same limits. Free-model
availability, tool support, and provider routing can change; record the exact
model and endpoint used. Nothing here requires NVIDIA hardware.

## The 13 tasks

Each row is a separate attempt in a fresh workspace. Omit `--task` to run the
whole suite, or select one task by its ID. The checks in the last column run
after the model finishes; it cannot see them while working.

| Lane | Task ID | What the model does | What the suite checks |
| --- | --- | --- | --- |
| Code | `python-expiry` | Repair inclusive expiry handling and add regression tests. | Zero, missing and null expiries, order, duplicates, and unchanged inputs. |
| Code | `node-idempotency` | Make a Node store handle retries, conflicts, and invalid input. | Stable IDs, independent stores, no unwanted mutation, and added tests. |
| Code | `go-worker-pool` | Repair a bounded worker pool across multiple Go files. | Parallelism limit, cancellation, result delivery, and race safety. |
| Code | `go-transfer-ledger` | Make transfers atomic and idempotent under concurrent calls. | Exactly-once effects, balances, conflicts, cancellation, and races. |
| Code | `arkade-add` | Add real `shfmt` support to a pinned arkade checkout. | Release URLs for five platforms, Go tests, and the README entry. |
| Tools | `stock-transfer` | Recover from a simulated stock revision conflict. | One correct transfer, a fresh read before retry, and reported counts. |
| Tools | `payment-recovery` | Resolve ambiguous payment timeouts for two fictional invoices. | Lookup before retry, exactly-once ledger effects, and final balances. |
| Tools | `ticket-routing` | Update one tenant's ticket despite an injected instruction. | Correct ticket and priority; every other ticket stays unchanged. |
| Evidence | `evidence-revisions` | Pick the newest approved configuration, leaving unknowns unknown. | Exact JSON, source citation, and a read of the authoritative file. |
| Evidence | `multilingual-evidence` | Reconcile Italian and Korean records without adopting a draft. | Exact Unicode owner, values, source, and JSON format. |
| Evidence | `long-context-retrieval` | Find the approved record among 360 distracting entries. | Correct record and values in strict JSON. |
| Exploratory | `statement-redact` | Remove human sender names from a synthetic bank-statement PDF. | Names absent from the PDF, with dates, amounts, balances, and other text retained. |
| Exploratory | `security-boundary` | Help with defensive telemetry while refusing credential theft. | Both decisions and a lightweight content check; this is a smoke test. |

The arkade task uses [shfmt](https://github.com/mvdan/sh), a real tool with a
saved release manifest, and a checkout from before arkade added it. The task
workspace omits `.git`, so an agent cannot inspect the later solution in its
history. A model may have seen arkade's real shfmt change during training, so
a pass can reflect recall rather than repository reasoning. Public tasks and
checks can likewise enter future training data. We do not download or execute
release binaries during the test.
The PDF and security cases need further validation before they can support
stronger claims.

The present coding harness exposes typed file/edit/test tools, **not a normal
shell-enabled OpenCode session**. That constraint is visible in every receipt
and may change how a model behaves. We plan a shell-enabled control before
making broad coding-agent comparisons.

## Try it

Each [release](https://github.com/alexellis/rigmark-quality/releases) will
include a runnable tarball and a SHA-256 checksum. You can use those instead
of cloning the repository; the remaining Docker and arkade setup is the same.
See [RELEASING.md](RELEASING.md) for the release process.

Use a disposable VM, for example a
[Slicer VM](https://github.com/slicervm/agent-skills), with Docker Community
Edition installed. Docker runs public and withheld checks
with networking disabled, a read-only root, and resource limits. Start with a
fresh VM or cold fork for each model and keep credentials out of reusable
snapshots.

```sh
git clone https://github.com/alexellis/rigmark-quality
cd rigmark-quality

git clone https://github.com/alexellis/arkade /tmp/rigmark-quality-arkade
git -C /tmp/rigmark-quality-arkade checkout --detach e5215097ce8d9340af060412663f7c7130c594dd

docker build -t rigmark-quality-runtime:0.2 quality_suite
./rigmark quality list
./rigmark quality selftest --arkade-root /tmp/rigmark-quality-arkade
./rigmark quality run --model MODEL_ID --task python-expiry \
  --endpoint http://MODEL_HOST:8000/v1 --auth-file none \
  --reasoning-effort low --output quality-results/local
./rigmark quality report --output quality-results/local
```

That command runs only `python-expiry` as a smoke test. Omit the `--task` flag
to attempt all 13 tasks and write a separate receipt for each.

`selftest` runs reference and broken controls. It should pass before you run a
model. The runner uses OpenAI-compatible chat completions and tool calls.

| Provider | Connection |
| --- | --- |
| Local vLLM, SGLang, llama.cpp, or similar | `--endpoint http://HOST:PORT/v1 --auth-file none` |
| OpenCode Zen or OpenRouter | `--endpoint URL --api-key-env MODEL_API_KEY` |
| [Toilgate](https://toilgate.o6s.io/) | `--toilgate`, after signing in locally |

For a bearer-key endpoint, pass the **name** of an environment variable,
never the key itself:

```sh
export MODEL_API_KEY='your key'
./rigmark quality run --model MODEL_ID --task go-worker-pool \
  --endpoint https://opencode.ai/zen/v1 --api-key-env MODEL_API_KEY \
  --reasoning-effort low --output quality-results/zen
```

For OpenRouter, use `--endpoint https://openrouter.ai/api/v1` and an API-key
environment variable. Select a current free model that supports tool calls.
These fixtures are synthetic. Do not send private code in custom tasks to a
free endpoint without checking that provider's data terms.
The runner sends `temperature=0`, `top_p=1`, a fixed seed, and the declared
output/step/time caps. Providers may ignore fields or route to another backend;
check the observed model and failure fields before comparing results.

By default, `report` prints a compact ASCII card per model and suite hash.
Use `--format json` for a machine-readable diagnostic matrix. Each task JSON
receipt records the requested and observed model, request limits, suite and
task hashes, runtime image, checks, elapsed time, tool trace, and stop reason.
The card deliberately separates **artefact passed** from **conversation
finished**: correct code followed by a reasoning loop is a distinct outcome.
The card includes no overall pass percentage and no hardware or quantisation
claim. Describe your serving appliance and quantisation separately, ideally
with a RigMark bench receipt.

## What CI checks

On every push to `master` and pull request, the [check workflow](.github/workflows/check.yml)
clones the pinned arkade revision, builds the Docker test image, compiles the
Python code, runs the governor unit tests, and runs `selftest`. That control
run checks the reference and deliberately broken cases for all 13 tasks.
CI also regenerates the historical pilot cards and checks that they match the
committed text. It does not call a model endpoint or measure model quality.
The separate [release-assets workflow](.github/workflows/release-assets.yml)
packages the CLI and checksum only when a release is published.

## First receipts

The [11 October pilot cards](examples/receipts/2026-10-11-pilot/cards.txt)
and [public JSON summaries](examples/receipts/2026-10-11-pilot/) show DeepSeek
V4 Flash, GLM-5.3-Flash, and Qwen3.8-27B FP8 task outcomes. They are **historical
protocol 0.1 examples**, with different thinking settings across models. Their
arkade task used a fictional CLI, so those observations are not results for
the current shfmt task. The summaries omit private conversation traces; use
them to see the receipt format, not to rank the models. We will add matched
runs on the current protocol as it settles.

## Help shape the suite

What small task would expose a failure you have actually seen in local coding
agents? Please comment on the [request-for-comments issue](https://github.com/alexellis/rigmark-quality/issues/1)
with a reproducible task, expected outcome, and a way to judge it independently.
We especially want cases involving multi-file edits, Go concurrency, tool
calls, completion and looping, quantisation regressions, document handling,
and multilingual inputs. A useful test is small enough to run locally and hard
to pass by merely sounding convincing. See [CONTRIBUTING.md](CONTRIBUTING.md)
for task design and [PROTOCOL.md](PROTOCOL.md) for the current limits.

The AI-generated [workflow illustration](docs/images/quality-workflow.png) and
editable [hero source](docs/images/rigmark-quality-hero.html) are included for
reuse with attribution.
