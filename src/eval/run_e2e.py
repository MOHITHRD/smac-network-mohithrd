"""
run_e2e.py - end-to-end evaluation of the agent as the Orchestrator will use it.

    python eval/run_e2e.py --cases eval/e2e.network.json --repeats 3 --label v1

The kit's run_eval.py checks tool OUTPUTS: it calls each tool itself, with the
arguments written in the task file, and compares the response with ground
truth. It records the model's final answer but does not score it, and it does
not record which tools the model chose.

This script scores the other half. For each case a model receives only the
prompt and the agent's tool list (names, descriptions, parameter
descriptions), chooses its own tools, and writes the answer - the same loop as
ask.py, the console and run_eval.py's `answer` line. Each trial is scored on
three things:

  tools   did the model call the expected tools, in that order?
  origin  did the first domain-tool call start within tolerance of the
          intended point? (catches a place name resolved to the wrong place)
  answer  does the answer contain at least one required phrase and none of
          the forbidden ones?

A trial passes when every check that applies passes. Each case runs
--repeats times, because the model's choices vary between runs. Everything is
logged to W&B, labelled with --label (for example v1 / v2 descriptions), so
before/after runs sit side by side.

This file is this agent's own evaluation code. It reuses the kit's plumbing
(llm, ui, smac) and does not modify it.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "application"))
import llm  # noqa: E402
import ui  # noqa: E402
from mcp.client import Client  # noqa: E402
from smac import haversine_m  # noqa: E402

COLUMNS = ["case", "trial", "prompt", "label", "router_model", "tools_called",
           "tools_ok", "geocode_matches", "origin_used", "origin_error_m",
           "origin_ok", "answer", "answer_ok", "passed", "problems"]

# Argument names that hold the starting point of a domain tool, in order of
# preference. The first domain-tool call that has one of these defines where
# the model actually started.
ORIGIN_KEYS = [("lat", "lon"), ("origin_lat", "origin_lon")]


def in_order(expected: list[str], called: list[str]) -> bool:
    """True when `expected` appears in `called` in order (other calls may sit
    between them)."""
    it = iter(called)
    return all(any(name == c for c in it) for name in expected)


def origin_of(calls: list[dict]) -> tuple[float, float] | None:
    for step in calls:
        if step["tool"] == "geocode_place":
            continue
        args = step.get("arguments") or {}
        for la, lo in ORIGIN_KEYS:
            if la in args and lo in args:
                try:
                    return float(args[la]), float(args[lo])
                except (TypeError, ValueError):
                    return None
    return None


def score(case: dict, trace: list[dict]) -> dict[str, Any]:
    calls = [s for s in trace if s.get("kind") == "call"]
    called = [s["tool"] for s in calls]
    answer = next((s["text"] for s in reversed(trace) if s.get("kind") == "answer"), "")
    errors = [s.get("text", "") for s in trace if s.get("kind") == "error"]
    problems: list[str] = list(errors)

    tools_ok = in_order(case.get("expected_tools", []), called)
    if not tools_ok:
        problems.append(f"expected tools {case.get('expected_tools')} in order, got {called}")

    matches = [
        f'{(s.get("arguments") or {}).get("place", "?")} -> '
        f'{s["result"].get("matched_name") or s["result"].get("status")}'
        for s in calls if s["tool"] == "geocode_place"
    ]

    origin_used, origin_err, origin_ok = None, None, None
    ref = case.get("origin")
    if ref:
        used = origin_of(calls)
        if used is None:
            origin_ok = False
            problems.append("no domain tool was called with a starting point")
        else:
            origin_used = f"{used[0]:.5f}, {used[1]:.5f}"
            origin_err = haversine_m(ref["lat"], ref["lon"], used[0], used[1])
            origin_ok = origin_err <= ref.get("tolerance_m", 300)
            if not origin_ok:
                problems.append(f"started {origin_err} m from the intended point "
                                f"(tolerance {ref.get('tolerance_m', 300)} m)")

    low = answer.lower()
    any_of = case.get("answer_any", [])
    none_of = case.get("answer_none", [])
    has_any = not any_of or any(p.lower() in low for p in any_of)
    has_none = [p for p in none_of if p.lower() in low]
    answer_ok = has_any and not has_none
    if not has_any:
        problems.append(f"answer contains none of {any_of}")
    if has_none:
        problems.append(f"answer contains forbidden {has_none}")

    checks = [tools_ok, answer_ok] + ([origin_ok] if origin_ok is not None else [])
    return {
        "called": called, "tools_ok": tools_ok, "matches": matches,
        "origin_used": origin_used, "origin_err": origin_err, "origin_ok": origin_ok,
        "answer": answer, "answer_ok": answer_ok,
        "passed": all(checks) and not errors, "problems": problems,
    }


async def run(args, cases: list[dict]) -> tuple[list[list], dict]:
    async with Client(args.url) as client:
        health = await client.call_tool("health", {})
    agent = ui.unwrap(health).get("agent", "agent")
    ui.AGENTS[:] = [{"id": agent, "domain": agent, "url": args.url}]
    agents = await ui.discover()

    rows: list[list] = []
    totals = {"trials": 0, "passed": 0, "tools_ok": 0, "answer_ok": 0,
              "origin_ok": 0, "origin_checked": 0}
    for i, case in enumerate(cases, 1):
        print(f'\n[{i}] {case["prompt"]}')
        for t in range(1, args.repeats + 1):
            try:
                trace = await ui.run_with_model({"text": case["prompt"]}, agents,
                                                model=args.router_model)
            except Exception as exc:  # noqa: BLE001 - record and carry on
                trace = [{"kind": "error", "text": ui.readable(exc)}]
            r = score(case, trace)
            totals["trials"] += 1
            totals["passed"] += r["passed"]
            totals["tools_ok"] += r["tools_ok"]
            totals["answer_ok"] += r["answer_ok"]
            if r["origin_ok"] is not None:
                totals["origin_checked"] += 1
                totals["origin_ok"] += r["origin_ok"]

            verdict = "PASS" if r["passed"] else "FAIL"
            print(f'  trial {t}: {verdict}  tools={r["called"]}'
                  + (f'  origin_error={r["origin_err"]} m' if r["origin_err"] is not None else ""))
            for m in r["matches"]:
                print(f"           geocode {m}")
            for p in r["problems"]:
                print(f"           - {p}")
            short = r["answer"] if len(r["answer"]) <= 240 else r["answer"][:240] + "..."
            print(f"           answer: {short}")

            rows.append([i, t, case["prompt"], args.label, args.router_model or llm.model_name(),
                         ", ".join(r["called"]), r["tools_ok"], "; ".join(r["matches"]),
                         r["origin_used"], r["origin_err"], r["origin_ok"], r["answer"],
                         r["answer_ok"], r["passed"], "; ".join(r["problems"])])
    return rows, totals


def main() -> int:
    parser = argparse.ArgumentParser(description="End-to-end evaluation through a model router.")
    parser.add_argument("--url", default=f"http://127.0.0.1:{os.environ.get('PORT', '8000')}/mcp")
    parser.add_argument("--cases", required=True)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--label", default="unlabelled",
                        help="condition name for W&B, e.g. v1, v2, explain-off")
    parser.add_argument("--router-model", default=None,
                        help="model that chooses the tools (default: LLM_MODEL)")
    parser.add_argument("--no-wandb", action="store_true", help="print only, for a dry run")
    args = parser.parse_args()
    cases = json.loads(Path(args.cases).read_text(encoding="utf-8"))

    try:
        print(f"Claude API: ok ({llm.check()})")
    except Exception as exc:  # noqa: BLE001
        print(f"Cannot start: {exc}")
        return 2

    run_ = None
    if not args.no_wandb:
        import wandb
        project = os.environ.get("WANDB_PROJECT", "reit7820-eval")
        entity = os.environ.get("WANDB_ENTITY") or None
        if "/" in project:
            entity, project = project.split("/", 1)
            os.environ["WANDB_ENTITY"], os.environ["WANDB_PROJECT"] = entity, project
        run_ = wandb.init(entity=entity, project=project, job_type="e2e",
                          config={"cases": Path(args.cases).name, "repeats": args.repeats,
                                  "label": args.label,
                                  "router_model": args.router_model or llm.model_name(),
                                  "match_strategy": os.environ.get("MATCH_STRATEGY", "M3")})

    rows, t = asyncio.run(run(args, cases))
    n = t["trials"] or 1
    summary = {
        "trials": t["trials"],
        "pass_rate": t["passed"] / n,
        "tool_selection_rate": t["tools_ok"] / n,
        "answer_rate": t["answer_ok"] / n,
        "origin_rate": (t["origin_ok"] / t["origin_checked"]) if t["origin_checked"] else None,
    }
    print("\n" + "  ".join(f"{k}={v:.2f}" if isinstance(v, float) else f"{k}={v}"
                           for k, v in summary.items()))

    if run_ is not None:
        import wandb
        run_.log({"trials_table": wandb.Table(columns=COLUMNS, data=rows),
                  **{k: v for k, v in summary.items() if v is not None}})
        run_.finish()
    return 0


if __name__ == "__main__":
    sys.exit(main())
