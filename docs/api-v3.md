# CEO Console v3 API

Generated for Phase 2b.

## Core

- `GET /api/dashboard-summary` - task counts, overdue counts, dispatch health.
- `GET /api/daily-brief` - legacy daily warnings and due tasks.
- `GET /api/daily-brief/v2` - operating brief with projects, finance, memory, coordinator state, risks, suggestions.
- `GET /api/risks` - project stall and overdue task risk alerts.
- `GET /api/health` - runtime config, paths, launchd, ACP scripts, tools, Obsidian sync paths.

## Commander

- `POST /api/commander/execute` - body `{ "intent": "...", "context": "..." }`; creates, routes, and dispatches a task.
- `GET /api/commander/status` - latest Commander queue, running tasks, and completed tasks.

## Tasks

- `GET /api/tasks` - list tasks; supports `q`, `project`, `status`, `priority`, `execution_state`, `order_by`.
- `POST /api/tasks` - create a task.
- `GET /api/tasks/<id>` - get one task.
- `PATCH /api/tasks/<id>` - update task fields.
- `DELETE /api/tasks/<id>` - delete a task.
- `POST /api/tasks/<id>/dispatch` - run one task.
- `POST /api/tasks/<id>/retry` - reset and rerun one task.
- `POST /api/tasks/<id>/route` - recalculate token-aware route.
- `POST /api/tasks/<id>/review` - body `{ "decision": "approve|reject", "comment": "..." }`.
- `POST /api/tasks/bulk-dispatch` - dispatch up to 50 task IDs.
- `POST /api/tasks/bulk-retry` - retry up to 50 task IDs.
- `POST /api/tasks/bulk-review` - approve or reject multiple review tasks.
- `GET /api/tasks/export` - CSV export.
- `GET /api/tasks/<id>/log-stream` - SSE execution log stream.
- `GET /api/tasks/<id>/execution-report` - JSON or `?format=markdown`.

## Cron

Cron callbacks validate `CRON_SECRET` when the environment variable is set. Send the secret through `X-Cron-Secret`, `Authorization: Bearer ...`, query `secret`, or JSON body `secret`.

- `POST /api/cron/register` - registers three Hermes cron jobs: daily brief, risk scan, weekly report.
- `GET /api/cron/list` - lists Hermes cron jobs, or fallback JSON jobs.
- `POST /api/cron/remove` - body `{ "name": "ceo-risk-scan" }`; removes a Hermes or fallback job.
- `POST /api/cron/daily-brief` - receives daily brief callback and stores a `cron_reports` row.
- `POST /api/cron/risk-scan` - receives risk scan callback and stores a `cron_reports` row.
- `POST /api/cron/weekly` - receives weekly report callback and stores a `cron_reports` row.

If `hermes` is unavailable, registrations are written to `~/.hermes/cron/` when present, otherwise `data/hermes-cron/`.

## Knowledge Hub

- `GET /api/hub/memory` - Hermes `MEMORY.md` and `USER.md`.
- `GET /api/hub/skills` - Hermes skill frontmatter summary.
- `GET /api/hub/agents` - Claude agent frontmatter summary.
- `GET /api/hub/coordinator` - Agent Coordinator state.
- `GET /api/hub/cross-tool-routing` - Hermes shared cross-tool routing Markdown.
- `POST /api/hub/export/memory` - exports memory Markdown to `~/Desktop/obsidian-inbox/`.
- `POST /api/hub/export/skills` - exports skill summary Markdown.
- `POST /api/hub/export/agents` - exports agent summary Markdown.
- `POST /api/hub/export/coordinator` - exports coordinator state Markdown.
- `POST /api/hub/export/routing` - exports cross-tool routing Markdown.

`GET /api/hub/export/<tab>` is also accepted for browser compatibility.

## Finance

- `GET /api/finance/overview`
- `GET /api/finance/transactions`
- `POST /api/finance/transactions`
- `DELETE /api/finance/transactions/<id>`
- `POST /api/finance/transactions/import-csv`
- `GET /api/finance/subscriptions`
- `POST /api/finance/subscriptions`
- `PATCH /api/finance/subscriptions/<id>`
- `DELETE /api/finance/subscriptions/<id>`
- `POST /api/finance/ocr`
- `GET /api/finance/ocr/status`
