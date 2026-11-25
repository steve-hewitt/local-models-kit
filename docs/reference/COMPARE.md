# Reading compare runs

`scripts/compare.ps1` / `scripts/compare.sh` run the same workload through every cell of the kit's matrix:

| | Direct (`ollama/...`) | Via Headroom (`headroom/...`) |
| --- | --- | --- |
| Flint | agent cell | agent cell |
| Qwen3-30B-A3B | agent cell | agent cell |

Plus a raw speed bench per model straight against Ollama's API. Reports land in `results/compare-<timestamp>.md`, with one log per agent cell next to them.

Prerequisites: the kit's setup has been run (the agent cells use the installed global OpenCode config, so without it the `headroom/...` cells have nothing to pick), both models are pulled, Ollama is running, and for the Headroom cells the proxy script is running in its own terminal. The harness checks what it can and skips or errors with a specific message rather than producing a misleading empty report.

## What each number is

- **Bench tok/s**: from Ollama's own `eval_count` / `eval_duration` counters, not wall clock. The script runs the same fixed prompt N+1 times per model and reports every run plus the median. The first run is a warm-up (it pays the model load) and is excluded from the median; the median is taken over the remaining N runs. Only comparable across runs on the same machine, same context size, same Ollama version. One skew to know: both kit models support thinking, and reasoning tokens count in `eval_count`, so decode tok/s partly measures how much each model reasons, not just how fast it generates.
- **Agent result**: pass means the hello-agent tests went green in a throwaway copy of the example. Tests going green is a weaker claim than "the intended fix": the per-cell log appends a diff of the final `calc.py` against the pristine example, so a human can check that a pass was the minimal fix and not a rewrite that special-cases the test inputs. The timestamp matters (driver updates, thermals, and what else the machine was doing all move these numbers).
- **Seconds**: wall time for the agent run itself. Model load is excluded: each cell first warms its model with a 1-token generate, reported separately as **Warm-up s**. Cells also interleave by model (direct and Headroom for one model, then the other), so neither route systematically pays a cold start the other avoided.
- **Test file untouched**: a SHA-256 check (sha256sum, shasum, or python3, whichever the platform has; the harness refuses to run the agent cells if none exists, because a check comparing two empty hashes would always say yes). The task prompt forbids editing the tests; a `NO` here means the model cheated or misunderstood, which is a finding about the model, not a harness bug.
- **Report header**: records each model's effective `num_ctx` from Ollama's `/api/show`, so the conditions of the run are on the record. The harness defaults to the context-pinned variants (`flint-opencode:latest`, `qwen-opencode:latest`) precisely so this number is the kit's 131072 and not whatever the server default happened to be.
- **Side traffic**: the kit config pins no `small_model`, so OpenCode's title and summary calls follow each cell's own route and model. If you pin one yourself, the Qwen cells also load that model and the Headroom cells leak traffic around the proxy, and the cell labels stop being true.

## What a compare run is not

One agent run per cell is a single sample. Models are stochastic, the task is tiny, and a laptop's thermals drift over a long session. Treat agent cells as "did it do the job this time", never as a ranking. If two cells differ and it matters, rerun. If it still matters, run the task three times per cell by hand and count passes; at that point you have the beginnings of a measurement instead of an anecdote.

Speed comparisons between routes need one extra caveat: Headroom compresses context, so its benefit shows up as smaller prompts on long, tool-heavy work, which a 30-second bug fix barely exercises. The hello-agent cells will mostly show Headroom costing a little latency, not saving anything. That is expected and honest; the savings case is a long session in a real repo, measured with `headroom dashboard` during the run.

## Suggested protocol for a decision-grade comparison

1. Fresh boot, nothing else heavy running, laptop plugged in and cool.
2. Start Ollama, pull both models, start the Headroom proxy script in its own terminal.
3. Run `compare` once, throw the numbers away (warm-up for you and the machine; the harness already discards each bench cell's first run and warms each agent cell, this is for everything else: thermals, caches, your own familiarity).
4. Run it twice more. Compare medians across the three reports.
5. Paste the final tables into `docs/reference/VALIDATION.md` with the date, and only then argue about defaults.
