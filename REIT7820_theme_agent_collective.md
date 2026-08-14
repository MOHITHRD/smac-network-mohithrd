# Thesis Theme: The Smart Mobility Agent Collective — Building and Evaluating LLM Agents for Intelligent Transport

**Theme leads:** Dr Kai Li Lim & Dr Chengbo Zheng
**Teaching team:** 2 theme leads + 2 tutors
**Discipline area:** Data Science / Applied AI
**Cohort size:** 55 students (individual projects)

## Overview

Large language model (LLM) agents — AI systems that reason, call tools, and act autonomously — are transforming how software is built. In this theme, you will not merely *use* AI: you will **design, build, and scientifically evaluate your own LLM agent**, and prove it works by plugging it into a live multi-agent ecosystem alongside your peers' agents.

Each student selects one of the **domains** below and, within it, individually scopes, designs, and builds an agent that occupies its own distinct capability slot in a shared smart-mobility ecosystem for South East Queensland. You will build your agent on the Claude API (individual API budget provided), sourcing your own open dataset(s) as part of your project scoping. Your agent **is itself an MCP server**: you implement it to speak the **Model Context Protocol (MCP)** — the industry-standard interface for agent interoperability — following a fixed specification published in Week 1. A starter kit (skeleton MCP server, Claude API wiring, open-dataset shortlist) is provided so you write your first working tool call in Week 1, not Week 4.

### Domains (Semester 2, 2026)

| Domain | Focus | Example open data sources | Indicative headcount |
|---|---|---|---|
| **EV Charging Infrastructure** | Charging station availability, reliability, routing/range feasibility | OpenChargeMap API (global registry, free key); Queensland EV Super Highway dataset (data.qld.gov.au) | 8–10 |
| **Public Transport Journey Planning** | Multi-modal trip planning, real-time PT data, network accessibility | Translink SEQ GTFS (static schedules/stops/routes); Translink GTFS-Realtime (live vehicle positions, trip updates, service alerts) | 8–10 |
| **Transport Policy & Fares** | Fare structures, policy impact analysis, patronage modelling | Translink GTFS fare data; Queensland Open Data Portal patronage/policy datasets | 8–10 |
| **Demand, Equity & Mobility Analytics** | Travel demand patterns, transport equity, socio-spatial analysis | Queensland vehicle registration by suburb/postcode (data.qld.gov.au); ABS Census DataPacks/Data API (SA2-level demographics, SEIFA) | 8–10 |
| **Network & Routing Infrastructure** | Map/network data, multi-modal routing, geospatial services | OpenStreetMap via Overpass API / OSMnx | 8–10 |
| **Weather, Demand & Forecasting** | Demand/weather-sensitive mobility patterns, short-term forecasting overlays | Bureau of Meteorology open data; Translink patronage trends; OpenChargeMap usage patterns | 5–7 |
| **Propose Your Own** | A student-defined domain within smart mobility, subject to theme-lead approval | Student-sourced, must be openly licensed with no personal data | up to 3 |

Domains define the *ecosystem role* your agent will play — the specific dataset, query scope, and technical angle within your domain is yours to define and justify at Week 3 scoping. Capability overlap between students in a domain is permitted (see "Your thesis contribution" below). Domains are capped at indicative headcounts to keep the final Interoperability Showcase functionally diverse; if a domain is oversubscribed, allocation will run first-come alongside a short pitch paragraph.

The semester culminates in a live **Interoperability Showcase (Week 12)**: an orchestrator agent discovers and calls every student's agent in real time to solve composite mobility problems it has never seen. Your agent either responds correctly, live, or it doesn't — there is nothing to script and nothing to pre-record. Given cohort size, the Showcase runs as two heats (see Logistics below).

## Logistics: teaching team & sessions

- **Friday 12–2pm (whole cohort):** briefing sessions — not weekly. Confirmed dates: **Week 1 (kickoff, this Friday)**, **Week 3** (scoping/domain framing), **Week 7** (sprint review framing), **Week 9** (handshake test framing), **Week 12** (Showcase day). No Friday session in other weeks — your workshop tranche is your main weekly contact point.
- **Weekly workshops — choose one tranche:**
  - **Tranche A — Wednesday 10am–12pm**
  - **Tranche B — Thursday 6pm–8pm**
  - Sign up for whichever fits your timetable; both tranches run every domain, so your tranche choice is independent of your domain choice. Workshops are active studio sessions, not lectures — come with your laptop and current blocker.
- **Supervision:** each tranche has an anchor pair from the teaching team each week, with the full team (both theme leads + both tutors) available across Ed and both tranches for domain-specific questions.
- **Week 12 Showcase** runs as two heats aligned to tranches, so your regular workshop supervisors are the ones running your heat.

## Your thesis contribution

"I built an agent" is engineering; your thesis requires research. Every project in this theme therefore centres on a **controlled empirical evaluation** of your own agent. As part of your Week 3 scoping, you will define your own evaluation task set and ground truth for your domain (following a common schema published in Week 1, so results are comparable across the cohort), then select **one independent variable from a fixed menu** to study systematically:

1. **Prompt architecture** — zero-shot vs few-shot vs structured reasoning scaffolds
2. **Model tier** — cost–accuracy frontier across Claude model sizes
3. **Tool schema & description design** — how naming, descriptions, and schema structure change whether and how your agent is selected and used (every student also submits a v1/v2 pair of tool descriptions, giving you built-in before/after data)
4. **Robustness** — behaviour under ambiguous, out-of-scope, or adversarial queries

The menu is a scaffold, not a cage — a reporting template accompanies each option, so your effort goes into the experiment, not into inventing a methodology from scratch. Prompt and context engineering are not soft skills in this theme — they are your **independent variables**, and the rigour of your experimental design is a primary grading differentiator.

Note that **capability overlap within a domain is expected**: several students may build, say, charging-availability agents. Your edge comes from data choices, tool design, and description quality — at the Showcase, the Orchestrator selects among overlapping agents based on your descriptions and observed reliability, so earning selection is part of the game.

High-performing students will produce work suitable for submission to international conferences, with mentoring from the theme leads toward publication.

## Who this theme suits

Individual projects scale to your background. Strong programmers can pursue multi-step tool orchestration, evaluation harness design, or agent safety and guardrails. Students with lighter coding backgrounds can deliver a rigorous agent built primarily through prompt architecture, dataset curation, and systematic evaluation. All students need curiosity about how LLMs actually behave — and the discipline to test claims with evidence.

## Assessment alignment

- **Week 3 — Project Scoping & Architecture:** your domain, capability slot, dataset selection, agent architecture, and evaluation task design
- **Week 7 — Live Sprint Review:** demonstrate your working agent prototype from your laptop; state your biggest technical blocker
- **Weeks 9–10 — Protocol Handshake Test:** mandatory conformance check of your agent against the shared MCP specification
- **Week 12 — Interoperability Showcase:** live plugfest; your agent operates within the collective in real time
- **Week 14 — Capstone Project Report:** your agent design, empirical evaluation, and results

## What is provided

- Individual Claude API budget per student (with a cost-aware engineering guide — token economics is a learning outcome, not an obstacle)
- A starter kit: skeleton MCP server, Claude API wiring, and a shortlist of open transport/EV datasets (GTFS, OpenChargeMap, ABS, and others) to select from
- The MCP interface specification and the common evaluation-task schema (Week 1) — you author your own task instances and ground truth within it
- A self-serve conformance test harness — the same one that powers the Week 12 Showcase — so you can verify your agent's protocol compliance any time from Week 9
- Studio-style contact hours run as active working sessions, not passive lectures

**Prerequisite pathway:** REIT6811 (research methods) recommended.
