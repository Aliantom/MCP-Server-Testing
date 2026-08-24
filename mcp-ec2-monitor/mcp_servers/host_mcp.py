#!/usr/bin/env python3
"""
host-health MCP server (stdio transport).

Exposes READ-ONLY tools about the local EC2 instance. Deliberately has no
shell/exec tool: log contents flow into the model's context, so an attacker
who can write to your logs can attempt to steer the agent. Everything here
is a fixed command with a constrained argument surface.

Run standalone for a smoke test:
    python3 host_mcp.py
Inspect with the MCP inspector:
    npx @modelcontextprotocol/inspector python3 host_mcp.py
"""

import os
import re
import shutil
import subprocess

import httpx
from fastmcp import FastMCP

mcp = FastMCP("host-health")

# --- guardrails -------------------------------------------------------------

# Only these units can be queried. Add yours; never make this a free-form arg.
ALLOWED_UNITS = set(
    filter(None, os.environ.get("ALLOWED_UNITS", "nginx,prod-api,docker").split(","))
)

# Health endpoints the agent may GET. Loopback / private ranges only.
ALLOWED_HEALTH_HOSTS = set(
    filter(None, os.environ.get("ALLOWED_HEALTH_HOSTS", "127.0.0.1,localhost").split(","))
)

MAX_OUTPUT = 4000  # chars; keep tool results small — they cost tokens every turn


def _clip(text: str) -> str:
    return text[-MAX_OUTPUT:] if len(text) > MAX_OUTPUT else text


def _run(cmd: list[str], timeout: int = 10) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return _clip((r.stdout or "") + (r.stderr or ""))
    except subprocess.TimeoutExpired:
        return f"ERROR: `{' '.join(cmd)}` timed out after {timeout}s"
    except FileNotFoundError:
        return f"ERROR: `{cmd[0]}` not found on this host"


# --- tools ------------------------------------------------------------------


@mcp.tool()
def list_monitored_services() -> str:
    """List the systemd units this server is permitted to report on."""
    return "\n".join(sorted(ALLOWED_UNITS)) or "(none configured)"


@mcp.tool()
def service_status(name: str) -> str:
    """Current status of a systemd unit. Only allow-listed units are permitted.

    Args:
        name: unit name, e.g. "prod-api" or "nginx"
    """
    unit = name.removesuffix(".service")
    if unit not in ALLOWED_UNITS:
        return f"ERROR: '{unit}' is not in the allow-list. Call list_monitored_services()."
    return _run(["systemctl", "status", "--no-pager", "--lines=20", unit])


@mcp.tool()
def service_logs(name: str, minutes: int = 15, grep: str = "") -> str:
    """Recent journald logs for an allow-listed unit.

    Args:
        name: unit name
        minutes: how far back to look (1-180)
        grep: optional case-insensitive substring filter
    """
    unit = name.removesuffix(".service")
    if unit not in ALLOWED_UNITS:
        return f"ERROR: '{unit}' is not in the allow-list."
    minutes = max(1, min(int(minutes), 180))
    cmd = ["journalctl", "-u", unit, "--since", f"-{minutes}min", "--no-pager", "-n", "300"]
    if grep:
        cmd += ["--grep", re.escape(grep)]
    return _run(cmd, timeout=20)


@mcp.tool()
def disk_usage() -> str:
    """Filesystem usage for all mounted filesystems (df -h)."""
    return _run(["df", "-h"])


@mcp.tool()
def memory_usage() -> str:
    """Memory and swap usage (free -h)."""
    return _run(["free", "-h"])


@mcp.tool()
def load_and_top_processes(count: int = 10) -> str:
    """Load average plus the top processes by CPU.

    Args:
        count: how many processes to return (1-25)
    """
    count = max(1, min(int(count), 25))
    load = ""
    try:
        with open("/proc/loadavg") as fh:
            load = "loadavg: " + fh.read().strip() + "\n\n"
    except OSError:
        pass
    ps = _run(["ps", "-eo", "pid,pcpu,pmem,etime,comm", "--sort=-pcpu"])
    lines = ps.splitlines()[: count + 1]
    return load + "\n".join(lines)


@mcp.tool()
def app_health(url: str) -> str:
    """GET an internal health endpoint and return status code plus body.

    Args:
        url: full URL; host must be in ALLOWED_HEALTH_HOSTS
    """
    from urllib.parse import urlparse

    host = urlparse(url).hostname or ""
    if host not in ALLOWED_HEALTH_HOSTS:
        return (
            f"ERROR: host '{host}' not permitted. "
            f"Allowed: {', '.join(sorted(ALLOWED_HEALTH_HOSTS))}"
        )
    try:
        r = httpx.get(url, timeout=5.0)
        return f"HTTP {r.status_code}\n\n{_clip(r.text)}"
    except httpx.HTTPError as exc:
        return f"ERROR: request failed: {exc}"


@mcp.tool()
def recent_oom_kills() -> str:
    """Check the kernel ring buffer for recent OOM-killer activity."""
    if not shutil.which("journalctl"):
        return "ERROR: journalctl unavailable"
    return _run(
        ["journalctl", "-k", "--since", "-24h", "--no-pager", "--grep", "Out of memory"],
        timeout=20,
    )


if __name__ == "__main__":
    mcp.run()  # stdio transport — the agent spawns this as a subprocess
