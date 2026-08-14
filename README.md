# REIT7820 - Smart Mobility Agent Collective

Your starter kit. Three agent skeletons, one per domain, already wired to speak
MCP over Streamable HTTP and already fetching real Queensland open data. Pick the
one for your domain, change two lines, and it serves. The tools are yours to
build.

```
src/                            the kit - this is where you work
  agents/
    charging.py                 EV Charging agent            -> :8000
    public_transport.py         Public Transport agent       -> :8001
    policy.py                   Policy & Patronage agent     -> :8002
  eval/
    tasks.charging.json         your evaluation cases, one file per domain
    tasks.public_transport.json
    tasks.policy.json
    run_eval.py                 the runner. Don't edit
  smac.py                       identity checks, respond(), @guard. Read once
  common.py                     health and geocode_place, shared by every agent
  data.py                       open-data fetching, cached
  llm.py                        one ask() for the Claude API
  preflight.py                  checks your Python, dependencies, keys, datasets
  descriptions.md               your v1/v2 tool descriptions - a submission
  pyproject.toml                dependencies
  README.md                     what to change, and in what order

application/                    a console that calls your agent the way the
  ui.py                         Orchestrator will - discovers tools at runtime
  index.html                    and lets a model choose between them
  queries.py                    the questions the console offers

docker/
  compose.yml                   four services: three agents and the console
  Dockerfile                    one image, four commands
  .env                          YOUR KEYS GO HERE. git-ignored, never committed

docs/
  datasets.md                   open datasets, with licences and gotchas
  eval-schema.md                the evaluation format, shared across the cohort

REIT7820_mcp_spec_v1.0.1.md     the contract your agent must satisfy
REIT7820_theme_agent_collective.md
```

## Run it

Everything runs in Docker. Nothing to install locally, no virtual environment,
no Python version to match.

```bash
docker compose -f docker/compose.yml up --build      # first run builds, ~30s
open http://localhost:8080                           # macOS; or just visit the URL
```

Four containers start from one image: your three agents on ports 8000 to 8002,
and the console on 8080. The console waits for all three agents to answer a
health probe, so it never opens showing offline agents.

You only need the one for your own domain:

```bash
docker compose -f docker/compose.yml up charging     # just this one, no console
```

They answer immediately, but they answer nothing useful yet: each has a single
stub tool that declines. That is the floor - your agent is running and
conformant before you have written a line, so the first thing you build is a
tool, not a server.

To stop:

```bash
docker compose -f docker/compose.yml down            # add -v to discard cached datasets
```

### Your API keys

Two, both your own. Put them in `docker/.env`:

```bash
ANTHROPIC_API_KEY=...        # your agent runs on the Claude API
WANDB_API_KEY=...            # for logging your evaluation runs
WANDB_ENTITY=your-team       # optional
WANDB_PROJECT=your-project   # optional, defaults to reit7820-eval
```

```bash
docker compose -f docker/compose.yml up -d           # restart to pick them up
```

**`docker/.env`, not the repository root** - Compose reads `.env` from the
directory holding the compose file. It is git-ignored, and a key must never be
committed.

Without a Claude key everything still runs: your tools return their computed
facts, and only the written commentary is skipped. The W&B key is only needed
when you log an evaluation run.

### Check your setup

```bash
docker compose -f docker/compose.yml exec charging python /app/src/preflight.py --fetch
```

Verifies the Python version, the dependencies, your API key and every dataset,
then downloads them so nothing is fetched cold in front of an audience. Drop
`--fetch` for a check that downloads nothing.

## The console

Pick a domain, pick a question, press Run. Each run shows, in order: which tool
was selected on which agent and one sentence on why, the arguments it was given,
what came back, and the answer in prose.

**Nothing is hardcoded to a domain.** The console connects over Streamable HTTP,
calls `tools/list`, and gets back names, descriptions and parameter
descriptions. That is all the router ever sees — the same thing the Showcase
Orchestrator will see. A well described tool gets called and a vague one does
not, which is why description quality is graded.

The **Router model** menu picks which Claude tier chooses the tools. It is
separate from the model your agent uses for its own prose: at the Showcase the
Orchestrator's model is not yours to choose, and this is where you see the
difference a router makes.

Without a Claude key the console still runs, routing from each question's
scripted plan and labelling it as such on screen.

## The three domains

| Domain | Your file | Port | Data |
|---|---|---|---|
| EV Charging | `agents/charging.py` | 8000 | Queensland Electric Super Highway stations, CC BY 4.0 |
| Public Transport | `agents/public_transport.py` | 8001 | Translink SEQ GTFS, 13,098 stops and 926 routes, CC BY 4.0 |
| Policy & Patronage | `agents/policy.py` | 8002 | Translink monthly patronage, 116 months, CC BY 3.0 |

These are three separate servers, not one agent with nine tools. The domain is
part of your agent's name, and that constraint is what lets the Collective
compose at the Showcase instead of one agent doing everything.

## What you are building

An MCP server that the Orchestrator can discover and call. It never reads your
code - deciding whether to call you, it sees only your tool names, your
descriptions, and your parameter schemas. A well described tool gets called and
a vague one does not, which is why description quality is graded.

Three things your agent must get right:

- **Cite your sources.** Every response carries the dataset or API behind it.
- **Decline honestly.** A question outside your coverage gets a structured
  refusal, not an invented answer. Refusals are correct answers.
- **Compute your facts.** Numbers come from your code, never from a model. A
  figure you cannot trace to your data cannot be checked against ground truth.

### Proving it works

Your evaluation is yours to author: the questions, the tools you expect called,
and the answers you derived from the dataset yourself.

```bash
docker compose -f docker/compose.yml exec charging \
  python /app/src/eval/run_eval.py \
  --tasks /app/src/eval/tasks.charging.json --wandb
```

`--wandb` logs the run to your own Weights & Biases project, so runs sit side by
side and you can see what a change did rather than asserting it. The spec
requires those runs to be logged and the project linked in your report.

Full detail, and what to change first, is in `src/README.md`.
