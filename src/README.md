# REIT7820 Starter Kit - Python

A skeleton MCP agent wired up and running on real Queensland open data. Change
two lines and it serves. The rest is yours to build.

## Quickstart

Everything runs in Docker, from the repository root:

```bash
docker compose -f docker/compose.yml up --build
```

Your agent is then on http://localhost:8000/mcp. Check your setup any time:

```bash
docker compose -f docker/compose.yml exec charging python /app/src/preflight.py
```

To run an agent directly instead, you need **Python 3.10 or newer** - the MCP
SDK will not install on 3.9, and the error it gives is not obvious:

```bash
pip install "mcp>=2.0.0,<3" "httpx>=0.27"
python agents/charging.py      # http://127.0.0.1:8000/mcp
```

## The files

```
agents/            YOURS. Server wiring done.
  charging.py            EV Charging - one tool worked, as a reference  -> :8000
  public_transport.py    Public Transport               -> :8001
  policy.py              Policy & Patronage             -> :8002
eval/              YOURS. One file per domain: prompt, tools, output.
  tasks.charging.json  tasks.public_transport.json  tasks.policy.json
  run_eval.py          the runner. Don't edit.
common.py          health and geocode_place, shared by every agent
smac.py            identity checks, respond(), @guard. Read once; don't edit.
llm.py             one ask() for the Claude API
data.py            open-data fetching, cached
preflight.py       checks your Python, dependencies, key and datasets
descriptions.md    your v1/v2 tool descriptions - required submission
```

The skeletons run before you write anything: `docker compose up` starts all
three, each answering `health` and declining everything else. That is the floor
you build up from.

## What to change

Open `agents/<your domain>.py`.

| Week | Task |
|---|---|
| 1 | Set `AGENT_NAME` and `VERSION`, and deploy |
| 2 to 3 | Replace the worked tool with one of your own |
| 3 onwards | Add tools, up to five in total, and write your evaluation |

`AGENT_NAME` must be `smac-{domain}-{your approved slot}`, lowercase and
hyphenated. The kit checks the format at startup, so you find out now rather
than at the Week 9 handshake.

Capability overlap within a domain is expected - several students may build
similar tools. Your edge comes from your data choices, your tool design, and
your descriptions, not from claiming an exclusive slot.

## The shared tools

Two tools come from `common.py` rather than being written in each agent:

```python
common.register(mcp, agent_name=AGENT_NAME, version=VERSION,
                data_sources=[data.GTFS_LICENCE])
```

`health` is mandatory and its shape is fixed across the cohort, so there is
nothing to gain from fifty-five copies drifting apart. `geocode_place` is shared
because almost every spatial tool needs a coordinate, people ask questions using
place names, and a model that guesses one produces a number with no source.

The geocoder is opt-in: pass `geocode=False` if your tools take no coordinates,
as the policy agent does. A tool nobody in your domain needs still costs you - it
sits in the Orchestrator's menu and attracts calls meant for another agent.

`geocode_place` counts towards your five tools. `health` does not.

## Writing a description that gets you called

The highest-leverage thing you will do all semester, and it is graded.

The Orchestrator never reads your code. Deciding whether to call you, it sees
**only your tool name, your description, and your parameter descriptions**. Vague
ones mean a competing agent in your domain is picked instead - live, at the
Showcase.

A useful description covers four things:

1. **What it does**, concretely - not "handles charging queries".
2. **Coverage** - where your answers are valid.
3. **Freshness** - how live the data is.
4. **What it does *not* do.** Most-skipped, most valuable: it stops the
   Orchestrator calling you for questions you would answer badly.

Describe parameters too - they are the instructions for filling in your tool:

```python
lat: Annotated[float, Field(description="WGS84 latitude of the trip origin.")]
```

You submit a **v1 and a refined v2** of each description. Record both in
`descriptions.md` as you go.

## Proving it works

Each case in `eval/tasks.<domain>.json` is three things: the prompt, the tools
you expect called in order, and the output you expect back.

```json
[
  {
    "prompt": "Where can I charge near UQ St Lucia?",
    "tools": [{"name": "find_nearest_charger",
               "input": {"lat": -27.4981, "lon": 153.0112, "max_results": 1}}],
    "output": {"nearest": [{"name": "Brisbane", "distance_m": 9311}]}
  }
]
```

```bash
python eval/run_eval.py --tasks eval/tasks.charging.json
```

The runner calls the tools in order and checks that everything in `output`
appears in the response. Extra fields are fine - you assert only what you have
ground truth for.

Numbers must match exactly. Text matches if your string appears anywhere in the
response, case-insensitively, so you can assert that a refusal mentions South
East Queensland without pinning the exact wording.

`agents/charging.py` ships with `find_nearest_charger` written out in full, and
its two cases pass on a fresh clone:

```
Can I charge my EV at the Sydney Opera House?
  called find_nearest_charger
  PASS

Where can I charge my EV near the University of Queensland, St Lucia?
  called find_nearest_charger
  PASS

2/2 passed
```

That is your reference for what a finished tool and a real evaluation case look
like. The other two domains ship with a stub instead, so their second case fails
until you build the tool - which is the work.

Read the charging tool, then replace it. An agent that only serves the tool it
was given is a copy of the starter kit.

### Tracing runs in Weights & Biases

```bash
python eval/run_eval.py --tasks eval/tasks.charging.json --wandb
```

`--wandb` logs every case to your own W&B project - the prompt, the model your
agent is running on, the tools called, both outputs and the verdict - so runs sit
side by side and you compare across a change instead of diffing terminal output.

The model is read from your agent's `health`, not assumed, and recorded on every
row and in the run config. Model tier is one of the ablation options, so a result
is only comparable if you know which tier produced it. The default is
`claude-haiku-4-5`, the cheapest; set `LLM_MODEL` to compare against another.

Your own key, your own project:

```bash
WANDB_API_KEY=...                     # or run `wandb login` once
WANDB_PROJECT=reit7820-myagent        # optional, defaults to reit7820-eval
```

Set `WANDB_MODE=offline` to record locally and `wandb sync` later. Without a key
the run still completes; only the upload is skipped.

Derive every value in `output` from the dataset yourself. Taken from your own
agent's output it proves only that the agent agrees with itself.

## API keys

Your agent runs on the **Claude API**. Set one key:

Keys go in `docker/.env`, which Compose reads and git ignores:

```bash
ANTHROPIC_API_KEY=...        # your agent runs on the Claude API
WANDB_API_KEY=...            # only for `run_eval.py --wandb`
WANDB_ENTITY=your-team       # optional
WANDB_PROJECT=your-project   # optional
```

Never put a key in a file that git tracks - `.env.example` included.

Choose a tier with `LLM_MODEL`; whatever you use is reported in
`health.llm_backend`. Model tier is one of the four ablation options, so this is
your independent variable, not a constraint to work around.

With no key set, tools still return their computed facts and the written
commentary is replaced by a placeholder. That prose is commentary on numbers the
tool already calculated, so losing it should not take the tool down. A key that
is present but *rejected* does raise: that is a real fault.

Every call appends to `usage.jsonl` - tokens, latency, cost. That is your cost
dataset for the report; don't delete it.

## Two rules that are not negotiable

**Compute the facts; let the model write the prose.** Distances and ranking are
arithmetic. The model only explains a result it was handed. Never ask a model for
a number you can calculate - you cannot defend it, and it cannot be checked
against ground truth.

**Never guess a coordinate.** Asked to locate UQ St Lucia, a model returned a
point **261 m** from OpenStreetMap's. A recalled coordinate has no source and
cannot be cited. That is what `geocode_place` is for.

## A warning about MCP tutorials

Nearly all of them show:

```python
from mcp.server.fastmcp import FastMCP     # removed from our SDK version
```

Use:

```python
from mcp.server import MCPServer
```

`mcp` 2.x is the only line that speaks the protocol revision this course
requires. **Don't run `pip install -U mcp` during semester.**

## Deploying

stdio is fine locally, but **Streamable HTTP is required from Week 9**. Each
agent already serves it and reads `PORT` from the environment. Your agent needs a
URL the Orchestrator can reach, and keys must come from environment variables -
never a file in your repository.

## Checklist before Week 3

- [ ] `AGENT_NAME` is your approved slot, and the agent starts without raising
- [ ] At least one domain tool of your own
- [ ] Every tool and parameter has a real description - v1 written down
- [ ] Out-of-scope queries decline rather than inventing an answer
- [ ] Every response carries `sources`
- [ ] `.env` is not in your git history
- [ ] At least one evaluation case with an output you derived yourself, and
      `run_eval.py` passes it
