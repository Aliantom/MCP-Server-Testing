"""
Shared plumbing for both the heartbeat and the triage worker.

Loads .mcp.json, runs one agent turn with the Claude Agent SDK, and returns
the final text plus cost. Nothing here is monitoring-specific.

API surface note: the Agent SDK moves fairly quickly. If `query()` or
`ClaudeAgentOptions` field names drift, check:
    https://platform.claude.com/docs/en/agent-sdk/overview
    https://platform.claude.com/docs/en/agent-sdk/mcp
The result-message extraction below is written defensively so a renamed
message class won't silently return an empty string.
"""

from __future__ import annotations

import json
import os
import pathlib
from dataclasses import dataclass

import boto3
from claude_agent_sdk import ClaudeAgentOptions, query

ROOT = pathlib.Path(__file__).resolve().parent.parent
MCP_CONFIG = ROOT / ".mcp.json"
PROMPT_DIR = ROOT / "agent" / "prompts"

SNS_TOPIC_ARN = os.environ.get("SNS_TOPIC_ARN", "")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")

# Tools the agent may call. Wildcards are per-server. Anything not listed here
# is refused by the SDK before it reaches the MCP server — this is your second
# layer of defence after read-only IAM.
ALLOWED_TOOLS = [
    "mcp__cloudwatch__*",
    "mcp__host-health__*",
]


@dataclass
class AgentResult:
    text: str
    cost_usd: float | None
    num_turns: int | None


def load_mcp_servers() -> dict:
    """Read .mcp.json and return the mcpServers mapping.

    Env placeholders of the form ${VAR} are expanded so the file can be
    committed without secrets or account-specific values.
    """
    raw = MCP_CONFIG.read_text()
    expanded = os.path.expandvars(raw)
    return json.loads(expanded)["mcpServers"]


def load_prompt(name: str, **subs: str) -> str:
    """Load a prompt template from agent/prompts and substitute {placeholders}."""
    text = (PROMPT_DIR / f"{name}.md").read_text()
    return text.format(**subs) if subs else text


async def run_agent(
    prompt: str,
    model: str = "claude-haiku-4-5",
    max_turns: int = 12,
    system_prompt: str | None = None,
) -> AgentResult:
    """Run a single agent turn with the MCP servers attached."""
    options = ClaudeAgentOptions(
        model=model,
        mcp_servers=load_mcp_servers(),
        allowed_tools=ALLOWED_TOOLS,
        max_turns=max_turns,
        system_prompt=system_prompt,
    )

    text, cost, turns = "", None, None
    async for message in query(prompt=prompt, options=options):
        kind = type(message).__name__
        # Surface MCP connection failures early rather than getting a
        # confident answer built on zero tool calls.
        if kind == "SystemMessage" and getattr(message, "subtype", "") == "init":
            for server in getattr(message, "data", {}).get("mcp_servers", []):
                if server.get("status") not in ("connected", "ok", None):
                    print(f"WARN: MCP server {server.get('name')} -> {server.get('status')}")
        if kind == "ResultMessage" or getattr(message, "type", "") == "result":
            text = getattr(message, "result", "") or ""
            cost = getattr(message, "total_cost_usd", None)
            turns = getattr(message, "num_turns", None)

    return AgentResult(text=text.strip(), cost_usd=cost, num_turns=turns)


def publish(subject: str, body: str) -> None:
    """Send an alert to SNS. Falls back to stdout if no topic is configured."""
    if not SNS_TOPIC_ARN:
        print(f"[no SNS_TOPIC_ARN set] {subject}\n{body}")
        return
    sns = boto3.client("sns", region_name=AWS_REGION)
    sns.publish(
        TopicArn=SNS_TOPIC_ARN,
        Subject=subject[:100],  # SNS hard limit
        Message=body[:250_000],
    )
