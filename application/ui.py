"""
A demonstration console for the Smart Mobility Agent Collective.

This is a real MCP client. It speaks Streamable HTTP to three independent agent
servers, discovers their tools at runtime, and calls them. Nothing here is
stubbed, and the console has no special access: it sees exactly what the
Showcase Orchestrator will see, which is a list of tool names, descriptions and
parameter descriptions.

    python application/ui.py        # http://127.0.0.1:8080

Agent URLs come from the environment so the same file works whether the agents
are three local processes or three containers.
"""

from __future__ import annotations

import ast
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import anyio
from mcp.client import Client
from starlette.applications import Starlette
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Route

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import llm
import preflight
from queries import DOMAINS, QUERIES, by_id

HERE = Path(__file__).resolve().parent
MAX_STEPS = 4   # enough for geocode, two domain calls, then the answer

# Offered in the router picker. Model tier is one of the ablation options, so
# this is the knob that matters; the default comes first.
MODEL_TIERS = ["claude-haiku-4-5", "claude-sonnet-5", "claude-opus-5"]

AGENTS = [
    {"id": "charging", "domain": "EV Charging",
     "url": os.environ.get("CHARGING_URL", "http://127.0.0.1:8000/mcp")},
    {"id": "public_transport", "domain": "Public Transport",
     "url": os.environ.get("PT_URL", "http://127.0.0.1:8001/mcp")},
    {"id": "policy", "domain": "Policy & Patronage",
     "url": os.environ.get("POLICY_URL", "http://127.0.0.1:8002/mcp")},
]

def readable(exc: BaseException) -> str:
    """An unreachable agent surfaces as an ExceptionGroup wrapping the real error.

    "unhandled errors in a TaskGroup" says nothing useful when you are scanning
    fifty-five rows for the dead one, or reading back a retry record.
    """
    while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        exc = exc.exceptions[0]
    return f"{type(exc).__name__}: {exc}"


def agent_by_id(agent_id: str) -> dict | None:
    return next((a for a in AGENTS if a["id"] == agent_id), None)


async def discover() -> list[dict]:
    """Ask every agent who it is and what it can do. This is the MCP handshake."""
    async def one(agent: dict) -> dict:
        row = {**agent, "online": False, "tools": [], "health": None, "error": None}
        try:
            async with Client(agent["url"], read_timeout_seconds=20) as client:
                listing = await client.list_tools()
                row["tools"] = [
                    {
                        "name": t.name,
                        "description": (t.description or "").strip(),
                        "parameters": {
                            name: schema.get("description", "")
                            for name, schema in (t.input_schema or {}).get("properties", {}).items()
                        },
                        # Kept whole because the trace logs the schemas the Orchestrator
                        # saw at selection time, not a summary of them.
                        "input_schema": t.input_schema or {},
                    }
                    for t in listing.tools
                ]
                row["health"] = unwrap(await client.call_tool("health", {}))
                row["online"] = True
        except Exception as exc:
            row["error"] = readable(exc)
        return row

    rows: list[dict] = [None] * len(AGENTS)                        # type: ignore[list-item]

    async def fill(index: int, agent: dict) -> None:
        rows[index] = await one(agent)

    async with anyio.create_task_group() as group:
        for index, agent in enumerate(AGENTS):
            group.start_soon(fill, index, agent)

    return rows


def unwrap(result) -> dict:
    """A tool result arrives as JSON text. Turn it back into a dict."""
    if getattr(result, "structured_content", None):
        return result.structured_content
    for block in result.content or []:
        text = getattr(block, "text", None)
        if text:
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return {"text": text}
    return {}


def resolve(arguments: dict, results: list[dict]) -> dict:
    """Replace "$0.lat" with the value at that path in step 0's result."""
    def one(value):
        if not (isinstance(value, str) and value.startswith("$")):
            return value
        index, _, path = value[1:].partition(".")
        current = results[int(index)]
        for part in path.split("."):
            current = current[int(part)] if isinstance(current, list) else current[part]
        return current

    return {key: one(value) for key, value in arguments.items()}


async def call(agent_id: str, tool: str, arguments: dict) -> dict:
    agent = agent_by_id(agent_id)
    if agent is None:
        raise ValueError(f"no agent called {agent_id!r}")
    started = time.perf_counter()
    async with Client(agent["url"], read_timeout_seconds=50) as client:
        result = await client.call_tool(tool, arguments)
    payload = unwrap(result)
    return {
        "kind": "call",
        "agent": agent_id,
        "agent_domain": agent["domain"],
        "tool": tool,
        "arguments": arguments,
        "ms": int((time.perf_counter() - started) * 1000),
        "status": payload.get("status", "ok"),
        "is_error": bool(getattr(result, "is_error", False)),
        "result": payload,
    }


async def call_with_fallback(agents: list[dict], agent_id: str, tool: str,
                             arguments: dict) -> dict:
    """Call `tool`, falling back to another agent serving the same tool.

    Capability overlap is expected, so a failed call need not fail the
    query: another agent in the domain may serve a tool of the same name. With
    fifty-five student deployments, something is always down.

    An `out_of_scope` response is NOT a failure and never triggers a fallback -
    it is a correct answer, and retrying it elsewhere would punish the
    honesty the rubric rewards. Only transport errors and MCP tool errors do.

    Every attempt is recorded on the returned step, which is logged as
    `retry_behaviour`.
    """
    alternatives = [
        a["id"] for a in agents
        if a["online"] and a["id"] != agent_id
        and any(t["name"] == tool for t in a["tools"])
    ]
    attempts: list[dict] = []
    for candidate in [agent_id, *alternatives]:
        try:
            step = await call(candidate, tool, arguments)
        except Exception as exc:
            attempts.append({"agent": candidate, "outcome": readable(exc)[:160]})
            continue
        if step["is_error"]:
            attempts.append({"agent": candidate, "outcome": "mcp_error"})
            continue
        step["attempts"] = attempts            # empty unless a fallback happened
        return step

    return {
        "kind": "error",
        "tool": tool,
        "attempts": attempts,
        "text": (f"{tool} failed on every agent offering it "
                 f"({', '.join(a['agent'] for a in attempts)})."),
    }


ROUTER_SYSTEM = """You route a question to one tool belonging to one agent in a \
collective of independent agents.

You cannot see any agent's code. You see only tool names, descriptions and \
parameter descriptions. A well described tool gets \
called and a vague one does not.

Rules:
- Choose the single best next tool. Tools from different agents can be combined \
across steps, and often must be.
- If a tool needs a coordinate and the question gives only a place name, look \
the place up first with whichever agent can do that, then use the result.
- When you have enough to reply, answer in two or three sentences using only \
the numbers in the tool results. Never state a figure no tool returned.
- If a tool refused because the question is outside its coverage, say so \
plainly and stop. A refusal is a correct outcome, not a failure to work around.
- A tool marked [shared] is offered by several agents and behaves identically on \
each. Call it on the agent that owns the rest of the question, so the trace \
shows which agent the question really belongs to.

Reply with JSON only, no prose and no code fences, in one of these two shapes:
{"action": "call_tool", "agent": "<agent id>", "tool": "<tool name>", \
"arguments": {...}, "reason": "<one sentence on why this tool>"}
{"action": "answer", "text": "<your answer>"}"""


def tool_menu(agents: list[dict]) -> str:
    """The menu the router sees. Tools on more than one agent are marked.

    A shared utility such as the place lookup appears once per agent that
    registers it, byte for byte identical, and a model given two identical
    entries simply takes the first. Marking them lets the router pick the copy
    belonging to the agent the question is actually about.
    """
    seen: dict[str, int] = {}
    for agent in agents:
        for tool in agent["tools"] if agent["online"] else []:
            seen[tool["name"]] = seen.get(tool["name"], 0) + 1

    lines = []
    for agent in agents:
        if not agent["online"]:
            continue
        lines.append(f'\nAGENT {agent["id"]} ({agent["health"]["agent"]}) - {agent["domain"]}')
        for tool in agent["tools"]:
            if tool["name"] == "health":
                continue
            shared = " [shared]" if seen[tool["name"]] > 1 else ""
            lines.append(f'  {tool["name"]}{shared}: {tool["description"]}')
            for name, description in tool["parameters"].items():
                lines.append(f'      {name}: {description}')
    return "\n".join(lines)


def first_object(text: str) -> str:
    """The first balanced {...} in the text.

    Taking everything up to the last closing brace looks equivalent and is not:
    a model that emits one brace too many produces something that parses as
    neither JSON nor a Python literal, and the raw reply ends up on screen.
    """
    start = text.find("{")
    if start < 0:
        return text
    depth = 0
    in_string = escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start:index + 1]
    return text[start:]


def parse_router_reply(text: str) -> dict:
    body = text.strip()
    if body.startswith("```"):
        body = body.split("```")[1].removeprefix("json").strip()
    body = first_object(body)
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        # Models sometimes emit Python-style single quotes. Accept that rather
        # than showing the raw dict to whoever is watching the demo.
        parsed = ast.literal_eval(body)
        if not isinstance(parsed, dict):
            raise
        return parsed


async def run_with_model(query: dict, agents: list[dict],
                         model: str | None = None) -> list[dict]:
    """Let the model pick the tools, one step at a time, from descriptions alone.

    The model here is the *router's*, which is not the same thing as an agent's.
    Each agent writes its own prose with whatever it is configured with; this
    picks the tools. Keeping them separate is the point: at the Showcase the
    Orchestrator's model is not yours to choose.
    """
    menu = tool_menu(agents)
    trace: list[dict] = []
    transcript = f"QUESTION: {query['text']}\n\nAVAILABLE TOOLS:{menu}\n"

    for _ in range(MAX_STEPS):
        reply = await anyio.to_thread.run_sync(
            lambda: llm.ask(system=ROUTER_SYSTEM, user=transcript, max_tokens=900,
                            model=model)
        )
        if reply == llm.NO_KEY:
            raise RuntimeError(llm.NO_KEY)
        try:
            decision = parse_router_reply(reply)
        except (json.JSONDecodeError, ValueError, SyntaxError, IndexError):
            trace.append({"kind": "answer", "text": reply.strip()})
            return trace

        if decision.get("action") == "answer":
            # A model occasionally returns the right shape with an empty string.
            # Fall back to a line built from the last tool result rather than
            # showing a blank card.
            text = decision.get("text", "").strip()
            if not text:
                last = next((s["result"] for s in reversed(trace) if s["kind"] == "call"), {})
                text = headline(last) if last else "The model returned an empty answer."
            trace.append({"kind": "answer", "text": text})
            return trace

        trace.append({
            "kind": "route",
            "agent": decision.get("agent"),
            "tool": decision.get("tool"),
            "arguments": decision.get("arguments", {}),
            "reason": decision.get("reason", ""),
        })
        step = await call_with_fallback(agents, decision["agent"], decision["tool"],
                                        decision.get("arguments", {}))
        trace.append(step)
        if step["kind"] == "error":
            return trace
        transcript += (
            f'\nYou called {step["tool"]} on agent {step["agent"]} and it returned:\n'
            f'{json.dumps(step["result"])[:2500]}\n'
        )

    trace.append({"kind": "answer", "text": f"Stopped after {MAX_STEPS} tool calls."})
    return trace


async def run_scripted(query: dict) -> list[dict]:
    """Run the query's own plan. Used when no model is configured."""
    trace: list[dict] = []
    results: list[dict] = []
    for step in query["plan"]:
        arguments = resolve(step["arguments"], results)
        trace.append({
            "kind": "route",
            "agent": step["agent"],
            "tool": step["tool"],
            "arguments": arguments,
            "reason": "Scripted plan from the query catalogue; no model was asked.",
        })
        try:
            outcome = await call(step["agent"], step["tool"], arguments)
        except Exception as exc:
            trace.append({"kind": "error", "text": f"{type(exc).__name__}: {exc}"})
            return trace
        trace.append(outcome)
        results.append(outcome["result"])

    trace.append({"kind": "answer", "text": headline(results[-1] if results else {})})
    return trace


def headline(payload: dict) -> str:
    """One sentence about a tool result, without asking a model for it.

    When a key is configured the tools write their own prose and it is used
    verbatim. When none is, this states the leading figures from the payload so
    the console still says something true rather than pointing at the JSON.
    """
    if payload.get("status") == "out_of_scope":
        return payload.get("reason", "Out of scope for this agent.")
    for key in ("advice", "assessment", "summary", "interpretation"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip() and value != llm.NO_KEY:
            return value

    note = (
        " No model is configured, so this line was assembled in code rather than written."
        if llm.model_name() == "unconfigured"
        else " Assembled in code: this tool returns data, not prose."
    )
    for key, value in payload.items():
        if isinstance(value, list) and value and isinstance(value[0], dict):
            bits = ", ".join(
                f"{name} {item}" for name, item in list(value[0].items())[:3]
                if isinstance(item, (str, int, float))
            )
            return f"{len(value)} result(s) under '{key}'. Closest match: {bits}.{note}"
        if isinstance(value, dict) and value and all(isinstance(v, dict) for v in value.values()):
            parts = [
                f"{name} {inner['change_percent']:+.1f}%"
                for name, inner in value.items() if "change_percent" in inner
            ]
            if parts:
                return f"Change either side of the policy month: {', '.join(parts)}.{note}"

    numbers = ", ".join(
        f"{name} = {value}" for name, value in payload.items()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    )
    return (f"Returned {numbers}.{note}" if numbers
            else f"Returned {len(payload)} fields; see the response below.{note}")


async def index(request):
    return FileResponse(HERE / "index.html")


async def catalogue(request):
    agents = await discover()
    # One provider on this kit, so the picker offers the tiers you can select
    # with LLM_MODEL rather than asking the API what a key can reach.
    providers = [{"id": "anthropic", "models": MODEL_TIERS}] if llm.configured() else []
    return JSONResponse({
        "agents": agents,
        "domains": DOMAINS,
        "queries": [{k: q[k] for k in ("id", "domain", "text", "why")} for q in QUERIES],
        "model": llm.model_name(),
        "providers": providers,
        "key_hint": KEY_HINT,
    })


async def preflight_report(request):
    checks = await anyio.to_thread.run_sync(preflight.run_checks)
    return JSONResponse({"checks": checks})


async def run(request):
    body = await request.json()
    query = by_id(body.get("query_id", ""))
    if query is None:
        return JSONResponse({"error": "unknown query"}, status_code=404)

    agents = await discover()
    offline = [a["id"] for a in agents if not a["online"]]
    if offline:
        return JSONResponse({"error": f"agents offline: {', '.join(offline)}"}, status_code=503)

    model = llm.model_name(body.get("model") or None)
    wants_model = not body.get("scripted") and model != "unconfigured"
    started = time.perf_counter()

    if wants_model:
        try:
            trace = await run_with_model(query, agents, body.get("model") or None)
            mode = "model"
        except Exception as exc:
            trace = await run_scripted(query)
            trace.insert(0, {"kind": "error", "text": f"Model routing failed, ran the scripted plan instead. {exc}"})
            mode = "scripted"
    else:
        trace = await run_scripted(query)
        mode = "scripted"

    # Say which other agents offer the same tool, so a shared utility appearing
    # under one agent does not read as another agent lacking it.
    offered: dict[str, list[str]] = {}
    for agent in agents:
        for tool in agent["tools"] if agent["online"] else []:
            offered.setdefault(tool["name"], []).append(agent["id"])
    for step in trace:
        if step["kind"] in ("route", "call"):
            others = [a for a in offered.get(step.get("tool", ""), []) if a != step.get("agent")]
            if others:
                step["also_on"] = others

    return JSONResponse({
        "query": query,
        "mode": mode,
        "model": model if mode == "model" else None,
        "ms": int((time.perf_counter() - started) * 1000),
        "trace": trace,
    })


KEY_HINT = (
    "Add one line to docker/.env and restart the stack:\n"
    "    ANTHROPIC_API_KEY=...\n"
    "Compose reads .env from the folder holding compose.yml, not the repo root."
)

app = Starlette(routes=[
    Route("/", index),
    Route("/api/catalogue", catalogue),
    Route("/api/preflight", preflight_report),
    Route("/api/run", run, methods=["POST"]),
])


if __name__ == "__main__":
    import uvicorn

    # Print the same checks the UI serves, so a failure is visible in the logs
    # of whoever ran `docker compose up` rather than only in a browser.
    for check in preflight.run_checks():
        print(f"[{check['status']:>4}] {check['name']}: {check['detail']}", flush=True)

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8080")), log_level="warning")
