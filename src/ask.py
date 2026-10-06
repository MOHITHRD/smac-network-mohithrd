"""
ask.py - put any question to your agent the way the Orchestrator will.

    docker compose exec -T charging python ask.py < prompt.txt
    docker compose exec charging python ask.py "Where can I charge near Toowong?"

A model sees only your tools' names and descriptions, chooses which to call, and
answers from what they return - the same loop the console runs. Every step is
printed in order: the tool it chose and why, the arguments, what came back, and
then the final answer.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import textwrap
from pathlib import Path

import anyio

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "application"))
import llm  # noqa: E402
import ui  # noqa: E402

# Colour is on by default: `docker compose exec -T` gives the script no
# terminal to detect. Set NO_COLOR=1 to turn it off, e.g. when saving to a file.
COLOUR = not os.environ.get("NO_COLOR")
WIDTH = 78


def paint(text: str, *codes: str) -> str:
    styles = {"bold": "1", "dim": "2", "red": "31", "green": "32", "yellow": "33",
              "blue": "34", "magenta": "35", "cyan": "36"}
    if not COLOUR:
        return text
    return "".join(f"\033[{styles[c]}m" for c in codes) + text + "\033[0m"


def banner(title: str, colour: str) -> str:
    """A full-width rule with the section name in it, so sections stand apart."""
    label = f"━━ {title} "
    return "\n" + paint(label + "━" * (WIDTH - len(label)), "bold", colour)


def wrapped(text: str, pad: str = "  ") -> str:
    return "\n".join(textwrap.fill(line, WIDTH, initial_indent=pad, subsequent_indent=pad)
                     for line in text.splitlines() if line.strip())


def block(value, pad: str = "      ", limit: int = 4000) -> str:
    """Pretty JSON, indented under its heading. A long station list is cut short."""
    text = json.dumps(value, indent=2, ensure_ascii=False, default=str)
    if len(text) > limit:
        text = text[:limit] + "\n... (cut)"
    return "\n".join(pad + line for line in text.splitlines())


STATUS_COLOUR = {"ok": "green", "out_of_scope": "yellow"}


async def ask(question: str, model: str | None) -> int:
    try:
        llm.check()
    except RuntimeError as exc:
        print(paint(f"Cannot start: {exc}", "red"))
        return 2
    agents = await ui.discover()
    for agent in agents:
        if not agent["online"]:
            print(paint(f"Agent {agent['id']} is not answering at {agent['url']}: {agent['error']}", "red"))
            return 1
        tools = [t["name"] for t in agent["tools"] if t["name"] != "health"]
        print(paint(f"agent   {agent['health']['agent']}  ({', '.join(tools)})", "dim"))
    print(paint(f"router  {llm.model_name(model)}", "dim"))

    print(banner("QUESTION", "cyan"))
    print(wrapped(question))

    try:
        trace = await ui.run_with_model({"text": question}, agents, model)
    except Exception as exc:  # noqa: BLE001 - say what is wrong, not a traceback
        print(paint(f"\nCannot route the question: {ui.readable(exc)}", "red"))
        return 2

    if any(s["kind"] == "route" for s in trace):
        print(banner("TOOL CALLS", "yellow"))
    step = 0
    for s in trace:
        if s["kind"] == "route":
            step += 1
            print(("\n" if step > 1 else "") + paint(f"  Step {step}  ", "bold") + paint(s["tool"], "bold", "yellow"))
            print(paint("    why        ", "blue") + s["reason"])
            print(paint("    arguments", "blue"))
            print(block(s["arguments"]))
        elif s["kind"] == "call":
            status = s["status"] if not s["is_error"] else "error"
            colour = STATUS_COLOUR.get(status, "red")
            print(paint("    result     ", "blue")
                  + paint(status, "bold", colour)
                  + paint(f"  from {s['agent']}, {s['ms']} ms", "dim"))
            print(block(s["result"]))
        elif s["kind"] == "error":
            print(paint(f"    error      {s['text']}", "red"))
        elif s["kind"] == "answer":
            print(banner("ANSWER", "green"))
            print(wrapped(s["text"]))
    print()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Ask your agent a question, and watch each step.")
    parser.add_argument("question", nargs="?", help="the question; omit it to read stdin")
    parser.add_argument("--model", help="the router's model, e.g. claude-sonnet-5")
    args = parser.parse_args()

    question = (args.question or sys.stdin.read()).strip()
    if not question:
        parser.error("no question: pass one, or pipe a file in with < prompt.txt")
    return anyio.run(ask, question, args.model)


if __name__ == "__main__":
    sys.exit(main())
