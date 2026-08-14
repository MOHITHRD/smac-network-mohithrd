# Evaluation task schema

The shared format for evaluation cases, so results are comparable across the
cohort. You author the cases and the ground truth; the schema is fixed.

## The format

One file per domain: `eval/tasks.<domain>.json`, a JSON array of cases. Each case
is three things.

```json
[
  {
    "prompt": "Where can I charge near UQ St Lucia?",
    "tools": [
      {"name": "find_nearest_charger",
       "input": {"lat": -27.4981, "lon": 153.0112, "max_results": 1}}
    ],
    "output": {"nearest": [{"name": "Brisbane", "distance_m": 9311}]}
  }
]
```

| Field | What it holds |
|---|---|
| `prompt` | The question a user would ask. Not sent anywhere - it records what the case is testing |
| `tools` | The tools you expect called, in order, with their arguments |
| `output` | The parts of the response you expect back |

## Running it

```bash
python eval/run_eval.py --tasks eval/tasks.charging.json
python eval/run_eval.py --tasks eval/tasks.charging.json --wandb   # and log it
```

The runner calls each tool in order and checks that everything in `output`
appears in what came back. Extra fields in the response are ignored, so you
assert only what you have ground truth for. Exit code is non-zero if any case
fails.

Numbers, booleans and nulls must match exactly. Text matches if the expected
string appears anywhere in the actual one, case-insensitively:

```json
"output": {"status": "out_of_scope", "reason": "South East Queensland"}
```

passes for any refusal whose reason mentions the coverage area, and fails for one
that declined for some other reason. That lets you assert *why* a tool refused
without pinning the wording, which you should stay free to change.

## Ground truth

Every value in `output` must be derived from the dataset by you. Taken from your
own agent's response it proves only that the agent agrees with itself, which is
not evidence.

Three ways to get it, best first:

1. **Computed** - derive it deterministically from the open dataset. Record the
   rows and the formula so someone else can repeat it.
2. **Authoritative lookup** - the publisher states the answer; cite the record.
3. **Hand-labelled** - you judged it. Legitimate, but say so and say how.

## What a task set should cover

A set that tests only the happy path is a weak evaluation, and its authorship is
assessed. Worth covering:

- A value you calculated by hand from the dataset
- A question outside your coverage, where `output` expects a declined response
- Malformed input
- A multi-step case, where one tool's result feeds the next
- A faithfulness case: an `output` asserting the response does *not* carry detail
  your data cannot support

## Using it for your ablation

Your independent variable changes; the task set does not. That is the whole
design.

```bash
LLM_MODEL=claude-haiku-4-5 python agents/charging.py &
python eval/run_eval.py --tasks eval/tasks.charging.json --wandb

LLM_MODEL=claude-sonnet-5 python agents/charging.py &
python eval/run_eval.py --tasks eval/tasks.charging.json --wandb
```

Same cases, same ground truth, one variable moved. Two runs can both pass the
same number of cases while failing different ones - that difference is your
finding, and a difference you cannot explain is a bug rather than a result.

## Logging to Weights & Biases

Runs must be logged to your own W&B project, and the project linked in your
report. `--wandb` does it:

```bash
WANDB_API_KEY=...            # or run `wandb login` once
WANDB_ENTITY=your-team       # optional
WANDB_PROJECT=your-project   # optional, defaults to reit7820-eval
```

Each case becomes a row - prompt, tools called, expected and actual output,
verdict - alongside `passed`, `failed` and `pass_rate` for the run. Log one run
per value of your independent variable, so the comparison your report claims can
be seen rather than asserted.

`WANDB_MODE=offline` records locally without an account; `wandb sync` uploads
later.

Cost per run is in `usage.jsonl`: tokens, latency and USD per call.
