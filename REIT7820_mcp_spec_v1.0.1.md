# Smart Mobility Agent Collective — Agent Interface Specification

**Version:** 1.0.1 (LOCKED)
**Status:** Frozen — no further changes during semester
**Applies to:** all student agents in the REIT7820 Smart Mobility Agent Collective

---

## 1. Overview

Every student agent in the Collective is a **Model Context Protocol (MCP) server**. The theme-lead **Orchestrator** is an MCP client that discovers, calls, and composes student agents to answer composite mobility queries at the Week 12 Interoperability Showcase.

This specification defines the contract your agent must satisfy. Conformance is verified by the **handshake test** and is a hurdle requirement for presenting at the Showcase.

**Design principle:** the spec constrains the *interface*, never the *implementation*. How your agent reasons, which model calls it makes, how it structures its prompts, and how it processes its data are entirely yours — and are where your thesis contribution lives.

---

## 2. Protocol & Transport

- Agents MUST implement **MCP protocol revision 2025-11-25**. This is a deliberate pin: a major new revision (2026-07-28) is finalizing at the same time as this spec's freeze, rewriting core transport internals with limited SDK and community-tutorial maturity. We are staying on the well-supported prior revision for the full semester regardless of what ships after freeze.
- **Transport:** stdio is permitted for local development; **Streamable HTTP is required from the Week 9 handshake test onward** (needed for the Orchestrator to call ~50+ agents concurrently over a network at Showcase). stdio-only agents will not pass conformance.
- Agents MUST respond to MCP `initialize` and advertise the `tools` capability.
- SDK choice is free (Python and TypeScript SDKs are documented in the starter kit, targeting revision 2025-11-25; anything conformant to that revision is acceptable).

## 3. Agent Identity & Address

### 3.1 Identity

Every agent MUST declare, via MCP server metadata (`serverInfo`):

- `name`: `smac-{domain}-{slot}` — lowercase, hyphenated.
  - `{domain}` ∈ `charging | pt | policy | equity | network | weather | custom`
  - `{slot}` is your approved capability slot (e.g. `smac-charging-reliability`, `smac-pt-accessibility`)
- `version`: semantic version of your agent (e.g. `1.2.0`)

Your student identity is tracked in a separate theme-lead register, not in agent metadata — this keeps demo output and Showcase transcripts free of identifying information.

### 3.2 Address

MCP has no discovery mechanism: a client can only connect to an address it has been given. So:

- Every agent MUST be reachable at a **URL**, and that URL MUST be **registered with the theme lead by the Week 9 handshake test**. An unregistered agent cannot be called, and therefore cannot pass conformance.
- The URL is **not** part of your agent metadata. It may change at any time — redeploy, new host, new tunnel — by re-registering. Nothing in your code or `serverInfo` depends on it.
- The slot you register MUST equal your agent's `serverInfo.name`. The Orchestrator probes `health` and treats a mismatch as unreachable, because a mismatch means answers would be attributed to the wrong agent.
- No URL shape is prescribed. A public HTTPS endpoint, a tunnel, or a host and port on the venue network are all acceptable, provided the Orchestrator can reach it at the handshake test and at the Showcase.

## 4. Required Tools

### 4.1 `health` (mandatory, uniform)

Every agent MUST expose a tool named `health` taking no arguments, returning:

```json
{
  "status": "ok",
  "agent": "smac-charging-reliability",
  "version": "1.2.0",
  "data_sources": ["OpenChargeMap API", "QLD EV Super Highway dataset"],
  "llm_backend": "claude-haiku-4-5"
}
```

This is the target of the Week 9–10 handshake test and the Orchestrator's liveness probe.

### 4.2 Domain tools (student-designed)

- Agents MUST expose **between 1 and 5 domain tools** — the cap forces coherent design over tool sprawl.
- Tool names MUST be verb-first snake_case (`find_nearest_chargers`, `estimate_journey_time`).
- Every tool MUST have a complete JSON Schema for inputs (`inputSchema`) with descriptions on every parameter. Schema quality is assessed — the Orchestrator (and its LLM) selects tools *solely from your names, descriptions, and schemas*. If your descriptions are vague, your agent doesn't get called. This is by design: **tool description quality is prompt engineering, and it's graded.**
- **Description variants:** for each domain tool you MUST submit **two description versions** — `v1` (your initial draft) and `v2` (your refined version, informed by your own testing). Only `v2` is served live; `v1` is submitted alongside the final report. Writing a better description is the cheapest, highest-leverage improvement available regardless of programming background, and the paired versions feed your own before/after analysis.
- **Capability overlap is permitted and expected.** Several agents within a domain may expose similar capabilities. Uniqueness comes from your data choices, tool design, and description quality — not from claiming an exclusive slot. When capabilities overlap, the Orchestrator chooses whom to call based on your descriptions and observed reliability; earning selection over a competing agent is part of the game.

## 5. Data Conventions

To make agents composable, all agents MUST use these conventions in tool inputs and outputs:

| Concept | Convention |
|---|---|
| Coordinates | WGS84 decimal degrees, `{"lat": -27.4975, "lon": 153.0137}` |
| Timestamps | ISO 8601 with timezone (`2026-08-14T09:30:00+10:00`) |
| Distances | metres (integer) |
| Durations | seconds (integer) |
| Money | AUD, decimal string (`"0.50"`) |
| Geographic scope | South East Queensland; state your coverage in tool descriptions |
| Stop/route IDs | Translink GTFS IDs where applicable |
| Statistical areas | ABS ASGS SA2 codes (2021 edition) where applicable |

Every tool response MUST include a `sources` array citing the dataset or API behind the answer. This teaches data provenance and lets the Orchestrator attribute answers. The rest of the response shape is free per tool.

## 6. Behavioural Requirements

- **Timeouts:** any tool call MUST return (or error) within **45 seconds** — sized for realistic Claude-in-the-loop latency, while bounding composed Showcase queries to a sane total.
- **Errors:** agents MUST return MCP-standard tool errors with a human-readable message; they MUST NOT crash on malformed input. The handshake test includes deliberately malformed calls.
- **Statelessness:** tool calls MUST be independently valid — no hidden session state between calls. Internal caching is fine and encouraged.
- **Honesty about scope:** if a query is outside your coverage, your agent MUST say so in a structured response rather than inventing an answer. Behaviour under out-of-scope queries is part of the Showcase rubric.

## 7. Cost & Model Usage

- Agents MUST run on the **Claude API**, within your individual budget.
- Budget is **your own responsibility**, tracked against your issued key. There is no external cap that will stop a runaway loop — monitor your own usage. The starter kit logs tokens, latency and cost per call to `usage.jsonl`.
- Agents SHOULD default to the smallest model tier adequate for the task, and SHOULD use prompt caching for static system prompts and schemas. Cost–performance analysis is a first-class evaluation variable.
- The `health` response declares the model backend in use.

## 8. Security & Data Rules

- Agents MUST NOT require or transmit secrets, personal data, or scraped non-open data.
- All data sources MUST be openly licensed; sources are declared at Week 3 scoping and in the `sources` field at runtime.
- API keys are your own and MUST be read from environment variables, never committed to a repository. This applies to your Claude key, your Weights & Biases key, and any third-party service key.

## 9. Conformance & the Handshake Test

The handshake test verifies, per agent:

1. The agent is reachable at its registered URL, and the registered slot matches `serverInfo.name` (§3.2)
2. MCP `initialize` succeeds; metadata conforms to §3.1
3. `health` tool present and returns a conformant payload (§4.1)
4. All tools have complete input schemas (§4.2)
5. Data convention spot-checks (§5)
6. Malformed-input handling (§6)
7. Response-time budget (§6)

Checks 2 to 7 you can verify yourself at any time with the evaluation runner in the starter kit. Check 1 depends on the register, so only the theme lead can confirm it.

Passing the handshake is a **hurdle** (ungraded, pass/required) for Showcase participation. The Showcase reuses the same checks plus live composite queries.

**Agent snapshots:** your code and tool definitions are captured at **Week 7** (Sprint Review) and **Week 12** (Showcase) as part of normal assessment submission. Keep your repository history intact.

## 10. Evaluation

Conformance proves your agent answers. It does not prove your agent is *right*, and correctness is the thesis. You therefore submit an evaluation of your own agent, and the evidence behind it.

- You MUST define and submit **your own evaluation method**: the task set, the ground truth behind each expected answer, and how you derived it. The common schema is published in the starter kit so results are comparable across the cohort; the task instances and the ground truth are yours to author, and that authorship is assessed.
- Ground truth MUST be derived from your open dataset, **not** from your own agent's output. An expected value taken from the agent under test proves only that the agent agrees with itself.
- Each expected value MUST be traceable: record the dataset, the rows, and the calculation. Ground truth nobody can re-derive is not evidence.
- A task set that exercises only the happy path is a weak evaluation. Cover at least one question outside your coverage that should be declined, and one malformed input.

### Logging (Weights & Biases)

- Evaluation runs MUST be logged to **Weights & Biases**, under your own account and project. The starter kit's runner does this with `--wandb`.
- Log a run for each value of your independent variable, so the comparison your report claims can be seen rather than asserted. Two runs that score the same overall while failing different cases is a result — and that difference is only visible if both were recorded.
- Link your W&B project in your final report, readable by the teaching team at marking.

## 11. Orchestrator Instrumentation

*This section describes theme-lead infrastructure. It imposes no build requirements on you, but you should know your agent operates in an instrumented environment.*

The Orchestrator logs, for every composite query at the handshake test and Showcase:

| Field | Content |
|---|---|
| `query_id`, `timestamp` | Composite query identity and timing |
| `candidate_tools` | All tools visible to the Orchestrator at selection time |
| `selected_tool(s)` | Which agent and tool was chosen, and selection order |
| `selection_rationale` | The Orchestrator's stated reason for its choice |
| `call_outcome` | Success / MCP error / timeout / malformed response |
| `response_used` | Whether the result was incorporated into the final answer |
| `latency_ms`, `token_cost` | Per-call performance and cost |
| `retry_behaviour` | Fallback to alternative agents on failure, if any |

Purpose: transparent, evidence-based Showcase assessment — selection and reliability outcomes are visible to you rather than anecdotal. Trace data used for research analysis beyond assessment requires ethics approval.

## 12. Versioning of this Specification

- This spec is frozen and does not change during semester. Clarifications are announced on Ed.
- **Protocol revision note:** if MCP 2026-07-28 or later achieves broad SDK maturity during the semester, we will *not* migrate mid-course. Any adoption is a decision for the next offering.

---

### Decisions

| # | Decision | Resolution |
|---|---|---|
| D1 | Transport | stdio permitted for dev; Streamable HTTP required from Week 9 |
| D2 | Student ID in metadata | Separate theme-lead register, not in agent metadata |
| D3 | Domain tool cap | Between 1 and 5 |
| D4 | Response envelope | `sources` array mandatory; rest free |
| D5 | Tool timeout | 45 seconds |
| D6 | Protocol revision | Pinned to MCP 2025-11-25 |
| D7 | Research use of traces and artefacts | Requires ethics approval |
| D8 | Ablation menu | 4 options: prompt architecture / model tier / tool-schema & description design / robustness |
