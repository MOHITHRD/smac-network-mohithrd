"""
llm.py - one function, one model.

    from llm import ask
    text = ask(system="You are terse.", user="Explain this in one sentence.")

`ask()` is the only seam between your tools and a model. Set your key and it
works; there is nothing else to configure.

    ANTHROPIC_API_KEY=...

Choose a tier with LLM_MODEL, or per call:

    ask(system, user, model="claude-sonnet-5")

Model tier is one of the ablation options, so this is your independent variable.
Whichever you use is reported in health.llm_backend.

Every call appends a line to usage.jsonl - tokens, latency and cost. That file
is your cost dataset for the report; don't delete it.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import httpx

API_URL = "https://api.anthropic.com/v1/messages"
API_KEY = "ANTHROPIC_API_KEY"
DEFAULT_MODEL = "claude-haiku-4-5"
PRICE_PER_MTOK = (1.00, 5.00)          # USD per million tokens: input, output

USAGE_LOG = Path(__file__).with_name("usage.jsonl")
TIMEOUT_SECONDS = 30.0

NO_KEY = "(no API key configured - set ANTHROPIC_API_KEY to get written commentary)"


def configured() -> bool:
    """True if a key is present. Not configured is a valid state."""
    return bool(os.environ.get(API_KEY))


def model_name(model: str | None = None) -> str:
    """The model in use - reported in health.

    Never raises: health must answer even before a key is set, otherwise the
    Orchestrator's liveness probe fails for a reason unrelated to liveness.
    """
    if not configured():
        return "unconfigured"
    return model or os.environ.get("LLM_MODEL") or DEFAULT_MODEL


def ask(system: str, user: str, max_tokens: int = 1024, model: str | None = None) -> str:
    """Send one prompt and return the text.

    With no key this returns NO_KEY rather than raising. The prose a tool adds is
    commentary on facts it has already computed, so losing the commentary must
    not take down the whole tool.

    A key that is present but rejected still raises: that is a real fault, and
    hiding it would waste your afternoon.
    """
    if not configured():
        return NO_KEY

    model = model_name(model)
    started = time.perf_counter()
    response = httpx.post(
        API_URL,
        headers={"x-api-key": os.environ[API_KEY], "anthropic-version": "2023-06-01"},
        json={
            "model": model,
            "max_tokens": max_tokens,
            # cache_control marks the stable prefix so repeated calls are cheaper.
            "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            "messages": [{"role": "user", "content": user}],
        },
        timeout=TIMEOUT_SECONDS,
    )
    latency_ms = int((time.perf_counter() - started) * 1000)
    if response.status_code != 200:
        raise RuntimeError(f"anthropic {response.status_code}: {response.text[:300]}")

    data = response.json()
    text = "".join(b.get("text", "") for b in data["content"] if b.get("type") == "text")
    if not text.strip():
        raise RuntimeError(f"{model} returned no text - try a larger max_tokens.")

    usage = data.get("usage", {})
    _log(model, usage.get("input_tokens"), usage.get("output_tokens"), latency_ms)
    return text


def _log(model: str, tokens_in: int | None, tokens_out: int | None, latency_ms: int) -> None:
    usd = None
    if tokens_in is not None and tokens_out is not None:
        usd = round(tokens_in / 1e6 * PRICE_PER_MTOK[0] + tokens_out / 1e6 * PRICE_PER_MTOK[1], 6)
    record = {
        "model": model,
        "input_tokens": tokens_in,
        "output_tokens": tokens_out,
        "latency_ms": latency_ms,
        "usd": usd,
    }
    with USAGE_LOG.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")
