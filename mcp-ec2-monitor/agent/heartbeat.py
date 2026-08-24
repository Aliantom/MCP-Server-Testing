#!/usr/bin/env python3
"""
Scheduled health sweep. Run from a systemd timer every 15-30 minutes.

Cheap model, short leash. Emits the literal string OK when nothing is wrong,
which is the only reason this doesn't become an alert-fatigue machine: we
page on non-OK, not on "the model wrote some paragraphs".
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.runner import load_prompt, publish, run_agent  # noqa: E402

TARGET_NAME = os.environ.get("TARGET_NAME", "prod-api")
TARGET_INSTANCE_ID = os.environ.get("TARGET_INSTANCE_ID", "i-000000000000")
LOOKBACK_MINUTES = os.environ.get("LOOKBACK_MINUTES", "30")
HEARTBEAT_MODEL = os.environ.get("HEARTBEAT_MODEL", "claude-haiku-4-5")


async def main() -> int:
    prompt = load_prompt(
        "heartbeat",
        target=TARGET_NAME,
        instance_id=TARGET_INSTANCE_ID,
        minutes=LOOKBACK_MINUTES,
    )
    result = await run_agent(prompt, model=HEARTBEAT_MODEL, max_turns=12)

    cost = f"{result.cost_usd:.4f}" if result.cost_usd is not None else "?"
    print(f"turns={result.num_turns} cost=${cost} verdict={result.text[:80]!r}")

    if not result.text:
        publish(
            f"[MONITOR-ERROR] {TARGET_NAME} heartbeat returned nothing",
            "The agent produced no result. Check MCP server connectivity and "
            "journalctl -u monitor-heartbeat.service.",
        )
        return 1

    # Sentinel check. Anything other than a bare OK is an alert.
    if result.text.strip().upper().rstrip(".") == "OK":
        return 0

    publish(f"[{TARGET_NAME}] heartbeat finding", result.text)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
