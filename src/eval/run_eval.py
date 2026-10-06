"""
run_eval.py - run your evaluation against your live agent.

    python eval/run_eval.py --tasks eval/tasks.charging.json

A case is three things: the `prompt` a user would ask, the `tools` you expect
called in order with their arguments, and the `output` you expect back.

The runner calls the tools over MCP, exactly as the Orchestrator will, and
checks that everything in `output` appears in the response. Extra fields are
ignored, so you assert only what you have ground truth for.

Every run is logged to your own Weights & Biases project - the prompt, the
tools called, both outputs and the verdict - so runs sit side by side and you
can see what a change did. Set WANDB_API_KEY, and optionally WANDB_ENTITY and
WANDB_PROJECT to say where.

Before any case runs, the runner makes one small Claude API call and opens the
W&B run. A missing or rejected key stops it there, rather than after the cases.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

from mcp.client import Client

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "application"))
import llm  # noqa: E402
import ui  # noqa: E402

COLUMNS = ["prompt", "model", "tools", "expected_output", "actual_output", "passed", "final_response"]


def missing(expected: Any, actual: Any, path: str = "") -> list[str]:
    """Every leaf in `expected` that is absent or different in `actual`.

    Numbers, booleans and nulls must match exactly. Text matches if the expected
    string appears anywhere in the actual one, case-insensitively, so you can
    assert that a refusal mentions South East Queensland without pinning the
    wording you happened to use the day you wrote it.
    """
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return [f"{path or 'output'}: expected an object, got {type(actual).__name__}"]
        return [p for k, v in expected.items()
                for p in missing(v, actual.get(k), f"{path}.{k}" if path else k)]
    if isinstance(expected, list):
        if not isinstance(actual, list):
            return [f"{path}: expected a list, got {type(actual).__name__}"]
        if len(actual) < len(expected):
            return [f"{path}: expected at least {len(expected)} item(s), got {len(actual)}"]
        return [p for i, v in enumerate(expected) for p in missing(v, actual[i], f"{path}[{i}]")]
    if isinstance(expected, str):
        if not isinstance(actual, str) or expected.lower() not in actual.lower():
            return [f"{path}: expected text containing {expected!r}, got {actual!r}"]
        return []
    return [] if expected == actual else [f"{path}: expected {expected!r}, got {actual!r}"]


def brief(value: Any, limit: int = 400) -> str:
    """Compact JSON, truncated. A full station list buries the comparison."""
    text = json.dumps(value, default=str)
    return text if len(text) <= limit else text[:limit] + f"... (+{len(text) - limit} chars)"


async def call(client, name: str, arguments: dict) -> Any:
    response = await client.call_tool(name, arguments or {})
    text = response.content[0].text if response.content else "{}"
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"text": text}


async def final_response(prompt: str, agents: list[dict]) -> str:
    """The answer a model gives when it uses your tools for this prompt.

    The same loop as ask.py and the console: the model sees only your tool names
    and descriptions, as the Orchestrator will. It is recorded, not scored -
    pass or fail comes from the tool output above.
    """
    try:
        trace = await ui.run_with_model({"text": prompt}, agents)
    except Exception as exc:  # noqa: BLE001 - record it rather than stop the run
        return f"(no answer: {ui.readable(exc)})"
    return next((s["text"] for s in reversed(trace) if s["kind"] == "answer"), "(no answer)")


async def run(url: str, cases: list[dict]) -> tuple[int, list[list], str]:
    failed, rows = 0, []
    async with Client(url) as client:
        # Which model the agent is running on, asked of the agent rather than
        # assumed. Model tier is an ablation variable, so a result is only
        # comparable if you know which tier produced it.
        health = await call(client, "health", {})
        model = health.get("llm_backend", "unknown")
        print(f"model: {model}")

        # The agent under test, as the router will see it.
        name = health.get("agent", "agent")
        ui.AGENTS[:] = [{"id": name, "domain": name, "url": url}]
        agents = await ui.discover()

        for case in cases:
            print(f'\n{case["prompt"]}')
            problems: list[str] = []
            result: Any = {}
            called: list[str] = []

            for step in case.get("tools", []):
                try:
                    result = await call(client, step["name"], step.get("input") or {})
                except Exception as exc:  # noqa: BLE001
                    problems.append(f'{step["name"]} raised {type(exc).__name__}: {exc}')
                    break
                called.append(step["name"])
                print(f'  called {step["name"]}')

            expected = case.get("output", {})
            problems += missing(expected, result)
            print(f"  expected  {brief(expected)}\n  actual    {brief(result)}")

            if problems:
                failed += 1
                print("  FAIL")
                for problem in problems:
                    print(f"    {problem}")
                if isinstance(result, dict) and result.get("status") == "out_of_scope":
                    print(f'    the tool declined: {result.get("reason", "")}')
            else:
                print("  PASS")

            answer = await final_response(case["prompt"], agents)
            print(f"  answer    {answer if len(answer) <= 300 else answer[:300] + '...'}")

            rows.append([case["prompt"], model, ", ".join(called), brief(expected, 1000),
                         brief(result, 1000), not problems, answer])

    print(f"\n{len(cases) - failed}/{len(cases)} passed")
    return failed, rows, model


def check_claude() -> str:
    """One tiny real call, so a bad key fails here and not halfway through."""
    return llm.check()


def start_wandb(args):
    """Open the W&B run before the cases, so a bad key fails fast."""
    import wandb

    if not (os.environ.get("WANDB_API_KEY") or (Path.home() / ".netrc").exists()):
        raise RuntimeError("WANDB_API_KEY is not set.")

    # WANDB_PROJECT may be "project" or "entity/project". wandb validates the
    # variable from the environment before the explicit argument applies, so a
    # split has to be written back rather than only passed to init().
    project = os.environ.get("WANDB_PROJECT", "reit7820-eval")
    entity = os.environ.get("WANDB_ENTITY") or None
    if "/" in project:
        entity, project = project.split("/", 1)
        os.environ["WANDB_ENTITY"], os.environ["WANDB_PROJECT"] = entity, project

    return wandb.init(entity=entity, project=project,
                      config={"tasks": Path(args.tasks).name, "url": args.url})


def log_wandb(run, cases: list[dict], failed: int, rows: list[list], model: str) -> None:
    import wandb

    passed = len(cases) - failed
    run.config.update({"model": model})
    run.log({"cases": wandb.Table(columns=COLUMNS, data=rows), "passed": passed,
             "failed": failed, "pass_rate": passed / len(cases) if cases else 0.0})
    run.finish()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run your evaluation against a live agent.")
    # Inside a container PORT names that agent, so the eval finds it unaided.
    parser.add_argument("--url", default=f"http://127.0.0.1:{os.environ.get('PORT', '8000')}/mcp")
    parser.add_argument("--tasks", required=True)
    args = parser.parse_args()
    cases = json.loads(Path(args.tasks).read_text(encoding="utf-8"))

    try:
        print(f"Claude API: ok ({check_claude()})")
        wandb_run = start_wandb(args)
    except Exception as exc:  # noqa: BLE001 - say what is wrong, not a traceback
        print(f"Cannot start the evaluation: {exc}\n"
              "Set ANTHROPIC_API_KEY and WANDB_API_KEY in .env, then restart the agent.")
        return 2

    failed, rows, model = asyncio.run(run(args.url, cases))
    log_wandb(wandb_run, cases, failed, rows, model)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
