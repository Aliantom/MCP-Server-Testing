# MCP-Server-Testing

QTA MCP Server - Scoped Overview for Design Consultaiton

Core Purpose

MCP (Model Context Protocol) server that bridges AI assistants like Claude Code with QTA Router's query execution and job management APIs. Enables natural language interaction with a analytics system across 5 environments (prod1 prod2 etc). The hope is to give AI agents read-only powers over QTA by exposing 48 MCP tools across 5 environments. Eventually elevated access will slowly be allowed for the MCP server, to allow things for health and status monitoring and automatic fixes to prevent any service downtime or to automatically troubleshoot with observability and logging etc.

- Agents ask natural language questions → get grounded answers with citations
- Every derived metric includes a SNOWBALL explain-panel (WHAT/HOW/WHY/ACT/SOURCE)
- Live dashboard at /dashboard (16 sections, 144k HTML currently)
- Architecture pivot: originally planned as Lambda+Java17+SSE, actually running as ECS Fargate + Python 3.3 + streamable-http

- --
Current State:

- 48 MCP Tools deployed to AWS fargate in qta-dev account in three categories
### Category 1: Live QTA operations  (34 tools)

Fan out across 5 environments by default; pass 'env=' for single.

Job lifecycle (9): get_job_status, get_job_details, get_job_results_metadata, list_jobs, get_job_logs, get_job_request, get_job_metrics, get_job_storage, get_jobs_submitted

Catalog (7): list_query_models, get_query_model, list_domains, get_domain, get_external_availability, get_user_entitlements, get_user_info

System/Metrics (13): get_system_version, get_system_health, get_healthcheck, get_health_rollup, get_query_metrics, get_storage_summary, get_runtime_stats, get_queue_duration_by_hour, get_state_status_per_hour, get_max_queue_depth, get_user_storage, get_system_config, get_model_minute_metrics, get_model_results_metrics

Diagnostics (5): trace_job_lifecycle, audit_queue_capacity_margin, get_stuck_jobs_report, summarize_caller_activity, get_model_health_snapshot

### Category 2: Brain KB (6 + Router)

No env parament - query synced index of 17k jira tickets,
2.5k Gitlab MRs, 1.9k Confluence pages.

-  brain_search - full text across all 3 searches
-  brain_get_entity - fullbody by locator
-  brain_cross_reference - whorefrences htis entity
-  brain_weekly_changes - entities changed in the last N days
-  brain_sync_status - KB freshness + entoity counts
-  brain_extract_pocs - POCs from ticket/MR
-  brain_route_task - NLP dispatcher

-  ### Category 3: Composite Analysis (9+)
Multi-tool workflows bundled into one call.

- explain_job_failure
- trace_job_lifecycle
- get_health_rollup
- diff_across_envs
- audit_queue_capcity_margin
- get_stuck_jobs_report
- get_model_health_snapshot
- summarize_caller_activity
- list_enviornments
- describe_tool
- get_mcp_telemtry
- get_qta_glossory

##Architecture Stack

AI Agent (Claude Code, Kilo, Any internal AI interfacing CLI)
| MCP tools/call (stateless POST)
v
qta-mcp-skill (~/.claude/skills/qta-mcp)
|  auto-loaded in any QTA repo
v
Local proxy (dev) OR
 qta-mcp-proxy (SigV4 signing)
 |
 v
API Gateway Rest V1
| AWS_IAM auth, SigV4
v
VPC Link v1
|
v
Internal NLB
|
v
ECS Fargate (Python 3.13-slim, 0.5 vCPU / 2GB)
|
v
server/app.py (FastAPI + MCP SDK, /mcp ednpoint)
| -- registry.py (loads tools.json, dispatches
| -- fanout.py (asyncio.gather across 5 envs)
| -- identity.py (SID from APIGW / X-Proxied-User)
| -- nginx_mtls.py (GET-only + circuit breaker)
| -- server/brain/tools.py (6 Brain KB implementations)
|
v
Secrets Manager (NTSPKI mTLS cert)
|
v
QTA Router (ssl:443, mTLS)
|-- int
|-- beta
|-- prod1
|-- prod2
|-- shield

###AWS Details
- Account: qta-dev
- Partiion: aws-iso-f
- Profile- hci-aws via chap
- CDK STack: infra/stacks/mcp_stack.py
- Bootstrap: 10328bs6

- Local dogfood: uvicorn server.app:app --port 8765
-  Claude desktop config: .mcp.json

---

## How it interacts with AI (Current)
AI agents with the qta-mcp skill loaded can:

- Call MCP tools directly (no @agent switch needed)
- Get fan-out across 5 envs in parallel via asyncio.gather
- Recieve results capped at max_response_bytes per tool
- See SNOWBALL explain-panels on every derived metric

Read-only enforcement (3 Layers)

1. Router authz - MCP service DN gets read-only role
2.  NginxMtlsClient - POST/PUT/DELETE RAISE rEADoNLYvIOLATION
3.  tools.json -e every tool has mutates=false, method=get
---
Missing Features (High Priority Gaps)
1. GitLab MR diffs - brain_get_entity returns metadata, not file diffs
2. Confluence page versions - no ersion comparison or edit histoory
3. Source code search - cant search qta/qta repo source code
4. Metrics time-series - point-in-time only, no Cloudwatch Export
5. 3 ghost tools in rendery.py - get_job_events, get_system_status,
   get_cluster_info (allreplaced, but VP section not updated)

## Potential New Features (Opprotunities)

## Short Term (1 Week)
- QTA-13863 Brain integration epic - move to IN progress
- Gitlab MR diff tool (brain_get_mr_diff)
- Confluence page version comparison (brain_page_diff)
- Local smoke test in CI (.gitlab-ci.yml  smoke-mcp stage)

## Medium-term (2-4 Weeks)
- explain_model_drift composite - compare models across envs + ADrs
- generate_incident_report - auto-draft from cocerns + logs
- Snowball technique formalization (extract into reusabe skill)
- Code search integration - add Gitlab code search to brain_search
- qta-mcp skill for ~/qta repo (auto-load on product code repo)

## Long-term (1-2 Months)

- Job submission Phase 2 - design write auth model
- Performance testing
- Historical brain snapshots - time-series KB for trend analysis
- CI Pipeline status tool - direct pipeline queries (not MR inference)
- Synthetic test probes - per-nev health check via real query

### Composite Tool Ideas
- explain_model_drift - list_query_models across envs + brain_search ADRs
- explain_domain_issue - list_domains + avialability + list_jibs
- generate_incident_report - concerns + explain_job_failure + brain_search

### Skill Ecosystem
- ~/.claude/skills/qta-mcp - 48-tool catalog + 5 workflow tempaltes
- ~/.claude/skills/qta-brain - direct brian KB acces (jq, brainhq)
- Opprotunity: create qta-mcp skill for ~/qta repo (product code)
- Opprotunity: extract SNOWBALL explain-panel into reusable skill

- ---

## Where things are hosted
- Brain KB: ~/git/brain (canonical)
    -~/workspace/brain is a symlink (stale clone arhcived at
     ~/workspace/brain.stale-2026-09-16)
-QTA MCP Server: ~/git/MCP (qta/MCP Project)
  - Local dev: uvicorn server.app:app --port 8765
  - .mcp.json connects Claude Code to localhost
 
-QTA Product: ~/qta (Scala, the Router this server proxies)
-Deploy Target: qta-dev account, awqs-iso-f partition
-AWS Profile: hci-aws (chap profiles)

---

## Key Files

- server/tools.sjon - tool definitions  (MCP catalog + metadata)
- server/app.py - FastAPI app, /mcp + /dashboard routes
- server/registry.py - loads tools.json, dispatches calls
- server/fanout.py - asyncio.gather multi-env parallel exec
- server/identity.py - SID from APIGW context / X-Proxied-User
- server/cache.py - per-tool TTL response cache
- server/brain/tools.py - 6 brian KB tool implementations
- dashboard/collect.py - 12 tool data collections, 60s keep-warm loop
- dashbaord/insights.py - conern detetion, SNOWBALL EXPLAIN specs
- dashboard/render.py - 16-section HTML dashboard + value proposition
- dashboard/metrics-history.json - persisted CI history (B47a)
- infra/stacks/mcp_stack.py - CDK: APIGW Rest v1 + VPC Link + NLB + Fargate
- client/qta_mcp_proxy.py - SigV4 signing proxy for local dev
- tools/common/brainq.py - brain KB remote-first access (never full artifacts)

---

## Local Development

```bash
cd ~/git/MCP
source .venv/bin/activate
# Note: .venv is Python 3.12, pyprojec.toml says >=3.13
# Use .venv/bin/python for everything; flag 3.13-only Syntax

uvicorn server.app:app --port 8765 --reload
QTA_MCP_ALLOW_ANON=1 python -m server.app #testing mode
```

### Tests 

```bash
pytest -q              # 286 tests
pytest tests/integration/ --integration   # requires QTA access
```

### Lint + types

```bash
ruff check.
mypy server/
```

### Infra

```bash
cd infra && cdk synth
cd infra && cdk deploy --profile qta-dev
```

---

##Invariants (Enforced by Tests)

1. Every tool in tools.json has mutates =fales and method= GET
2. NginxMtlsClient rejects any non-GET verb
3. Local-only tools have qta_endpoint: null
4. Fan-out wraps per-env errors - one failing env must not fail the whole call
5. Results capped at max_response_bytes - oversize returns
   {truncated: true, preview: ..., per_env_size_bytes: ...}

---
### SNOWBALL Explain-Panel Framework

Every heuristic derived value uses 5 fields
- WHAT - plain-language meaning
- HOW - exact computation (tool + filter logic)
- WHY - Operational impact
- ACT - concrete next steps
- SOURCE - data origin

 Example: concern queue-depth: prod2

- WHAT: prod2 queue depth is 12 (jobs waiting)
- HOW: get_system_health(env="prod2") → workQueue=12, fires when >5
- WHY: arrival rate > service rate - capcaity issue
- ACT: Compare with engine-hot/engine-missing; wait or add workers
- SOURCE: insights.concerns() → queue-depth:prod2

---













- 286 passing tests, 4658 lines of server code, 4098 lines of test code
- Live dashboard at /dashboard with real-time fleet monitoring
- Read-only Phase 1 complete, enforced at 3 layers: router authz, app layer, test layer


Architecture Stack:
Client (Claude Code / Kilo / Any other AI CLI interface etc)
→qta-mcp-proxy (local SigV4 shim for AWS IAM auth)
  →
