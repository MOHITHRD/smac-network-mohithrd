# REIT7820 - Network & Routing agent

Your agent for the Smart Mobility Agent Collective: an MCP server that already
runs on real Queensland open data. The tools are yours to build.

## Files

```
src/agents/network.py         your agent - this is where you work
src/eval/tasks.network.json   your evaluation cases
prompt.txt                             a question for ask.py - write your own
src/descriptions.md                    your v1 and v2 tool descriptions - a submission
src/data.py                            add your dataset here; the place lookup is there already
src/                                   the rest is shared plumbing: read it, don't edit it
application/                           the console, which calls your agent the way the Orchestrator will
.env                                   your keys - git-ignored, never commit it
logs/                                  usage.jsonl (every Claude call) and W&B files
REIT7820_mcp_spec_v1.0.1.md            the contract your agent must satisfy
```

## Setup

Install Docker Desktop, then create `.env` at the repository root:

```bash
ANTHROPIC_API_KEY=...
WANDB_API_KEY=...
WANDB_PROJECT=reit7820-network     # optional, defaults to reit7820-eval
WANDB_ENTITY=...                 # optional, your W&B team
```

Both keys are required. Without a working `ANTHROPIC_API_KEY` nothing starts:
not your agent, the console, `ask.py` or the evaluation. Without
`WANDB_API_KEY` the evaluation does not run.

## Run

```bash
docker compose up -d --build                        # your agent on :8000, the console on :8080
docker compose exec network python preflight.py --fetch    # check Python, keys and datasets
open http://localhost:8080                          # the console
```

If `up` reports that your agent failed to start, `docker compose logs network`
says why. It is usually a missing or rejected key.

```bash
docker compose up -d --build network      # after you edit your code - a plain restart runs the old code
docker compose logs -f network            # your agent's log
docker compose ps                       # what is running
docker compose down                     # stop
```

## Build your agent

Open `src/agents/network.py`:

1. Set `AGENT_NAME` to `smac-network-<your approved slot>`, and `VERSION`.
2. Replace `estimate_route_distance`, a stub that declines, with your own tools:
   one to five, named verb-first in snake_case.
3. Rebuild with `docker compose up -d --build network`.

The Orchestrator never reads your code. It chooses tools from their names,
descriptions and parameter descriptions alone, and their quality is graded. A
good description says what the tool does, where it is valid, how fresh its data
is, and what it does **not** do. Record v1 and v2 of each in `src/descriptions.md`.

- Return through `respond(...)`, so every response carries `sources`.
- Decline what you cannot answer with `out_of_scope(...)`. Never invent an answer.
- Compute numbers in code, and let the model only write prose about them. Use
  `geocode_place` instead of letting a model recall a coordinate.

## Evaluate

Each case in `src/eval/tasks.network.json` holds a prompt, the tools you expect
called with their arguments, and the output you expect back:

```json
{
  "prompt": "How far is it by road to the Sydney Opera House?",
  "tools": [
    {"name": "geocode_place", "input": {"place": "Sydney Opera House"}}
  ],
  "output": {"status": "out_of_scope", "reason": "South East Queensland"}
}
```

Numbers must match exactly. Text matches if your string appears anywhere in the
response. Derive every expected value from the dataset yourself, never from your
agent's output. Include a question you should decline and one malformed input.

```bash
docker compose exec network python eval/run_eval.py --tasks eval/tasks.network.json
```

W&B logging is required: every run is logged to your W&B project, so runs sit
side by side. Each run first checks your Claude API key with one small call and
opens the W&B run. Then it runs the cases and logs them. If either key is
missing or rejected, it stops before the first case.

## Ask your agent anything

Write a question in `prompt.txt`, then:

```bash
docker compose exec -T network python ask.py < prompt.txt
```

A model sees only your tools' names and descriptions, picks which to call, and
answers from what they return, which is how the Orchestrator will use your agent.
Each step is printed in order: the tool chosen and why, its arguments, what it
returned, and then the answer. Add `--model claude-sonnet-5` after `ask.py` to
change the model doing the choosing; your agent's own model stays the same.

The question, the tool calls and the answer are printed in colour. To turn
colour off, for example when saving the output to a file, add `-e NO_COLOR=1`
after `exec`.

## Handshake test

The conformance check from the spec, and a hurdle for the Showcase. It connects
to your agent the way the Orchestrator does and runs six checks. Put the
`smac-handshake-test/` folder in the repository root, then:

```bash
docker compose run --rm handshake
```

It ends with `HANDSHAKE PASSED`, or tells you what to fix. It also writes
`handshake_report.json`, which you commit as your proof.

## Choose the model

Your agent runs on `claude-haiku-4-5` unless you choose another tier:
`claude-haiku-4-5`, `claude-sonnet-5` or `claude-opus-5`. The model in use is
reported by `health` and recorded with every W&B run.

To set it until you change it, add a line to `.env`, then restart:

```bash
LLM_MODEL=claude-sonnet-5
```

```bash
docker compose up -d network
```

To use it for one run only, set it on the command line:

```bash
LLM_MODEL=claude-sonnet-5 docker compose up -d network
docker compose exec network python eval/run_eval.py --tasks eval/tasks.network.json
docker compose up -d network              # back to the .env setting
```

Every Claude call your agent makes is appended to `logs/usage.jsonl`, with its
model, tokens and latency.
