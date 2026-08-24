#!/usr/bin/env python3
"""
Event-driven triage. Long-running systemd service.

CloudWatch alarm -> SNS -> SQS -> this worker -> stronger model does RCA
-> writes a diagnosis back to the alerts topic.

Long-polls SQS, so it costs essentially nothing while idle. This is the path
that should carry your urgent signal; the heartbeat is for slow drift.
"""

import asyncio
import json
import os
import sys

import boto3

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.runner import load_prompt, publish, run_agent  # noqa: E402

AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
QUEUE_URL = os.environ["ALARM_QUEUE_URL"]
TRIAGE_MODEL = os.environ.get("TRIAGE_MODEL", "claude-sonnet-5")

sqs = boto3.client("sqs", region_name=AWS_REGION)


def parse_alarm(body: str) -> dict:
    """Unwrap the SNS envelope and return the CloudWatch alarm payload."""
    outer = json.loads(body)
    inner = outer.get("Message", outer)
    if isinstance(inner, str):
        inner = json.loads(inner)
    return inner


async def handle(alarm: dict) -> None:
    name = alarm.get("AlarmName", "unknown-alarm")
    state = alarm.get("NewStateValue", "?")
    reason = alarm.get("NewStateReason", "")
    trigger = json.dumps(alarm.get("Trigger", {}), indent=2)[:2000]

    if state != "ALARM":
        print(f"skip {name}: state={state}")
        return

    prompt = load_prompt(
        "triage",
        alarm_name=name,
        reason=reason,
        trigger=trigger,
    )
    result = await run_agent(prompt, model=TRIAGE_MODEL, max_turns=25)

    cost = f"{result.cost_usd:.4f}" if result.cost_usd is not None else "?"
    print(f"triaged {name} turns={result.num_turns} cost=${cost}")

    publish(
        f"[TRIAGE] {name}",
        result.text or "Agent returned no diagnosis. Investigate manually.",
    )


async def main() -> None:
    print(f"triage worker polling {QUEUE_URL}")
    while True:
        resp = sqs.receive_message(
            QueueUrl=QUEUE_URL,
            MaxNumberOfMessages=1,
            WaitTimeSeconds=20,   # long poll
            VisibilityTimeout=300,
        )
        for msg in resp.get("Messages", []):
            try:
                await handle(parse_alarm(msg["Body"]))
            except Exception as exc:  # noqa: BLE001 — never let one bad msg kill the worker
                print(f"ERROR handling message: {exc}")
                publish("[MONITOR-ERROR] triage worker exception", str(exc))
            finally:
                sqs.delete_message(
                    QueueUrl=QUEUE_URL, ReceiptHandle=msg["ReceiptHandle"]
                )


if __name__ == "__main__":
    asyncio.run(main())
