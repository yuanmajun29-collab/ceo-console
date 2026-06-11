# CEO Console v3 Architecture

## Three Layers

CEO Console v3 is organized around three operating layers:

1. Web CEO cockpit
   - Vue 3 + Vite SPA mounted at `/app/`.
   - Shows brief, risks, task queue, business domains, Commander, Knowledge Hub, and health.
   - Keeps CEO actions simple: view status, issue intent, approve or reject.

2. Flask orchestration API
   - `src/routes.py` owns HTTP surfaces.
   - `src/tasks.py` stores task lifecycle and review state.
   - `src/dispatch.py` launches tool-specific execution workers and streams logs.
   - `src/commander.py` converts natural-language intent into routed tasks.
   - `src/risk_monitor.py` scans project stalls and overdue tasks.
   - `src/daily_brief.py` builds v2 operating summaries from projects, tasks, finance, memory, and coordinator state.
   - `src/scheduler.py` registers Hermes cron jobs and stores cron callback reports.

3. Local tool and knowledge substrate
   - Agent Coordinator in `~/company/.agent-coordinator` provides shared state and ACP scripts.
   - Hermes memory and skills under `~/.hermes/` provide memory, cron, and cross-tool routing knowledge.
   - Obsidian read path is exposed through `knowledge-base/`; export write path is `~/Desktop/obsidian-inbox/`.
   - SQLite at `data/ceo_console.db` stores tasks, decisions, finance records, subscriptions, and cron reports.

## Frontend Modules

- `CockpitHome.vue` - operating brief, KPIs, risk cards, decision queue, business domains.
- `AICommander.vue` - natural-language execution form and responsive execution queue/log view.
- `KnowledgeHub.vue` - memory, skills, agents, coordinator state, cross-tool routing, export controls, auto-refresh.
- `ops/Health.vue` - runtime, ACP, launchd, tools, Obsidian sync paths.
- `components/Sidebar.vue` - Naive UI menu navigation with collapsed mode.

## Backend Modules

- `config.py` - paths, task types, tool routing, runtime settings, ACP discovery helpers.
- `db.py` - SQLite schema initialization and migrations.
- `tasks.py` - task validation, task queries, status reconciliation, report rendering.
- `dispatch.py` - launchd state, task command execution, progress appenders.
- `tools.py` - local tool availability, quotas, launch support.
- `projects.py` - project discovery and repository governance signals.
- `finance.py` - transactions, subscriptions, receipt OCR.
- `daily_brief.py` - v2 brief aggregation.
- `risk_monitor.py` - project and task risk detection.
- `scheduler.py` - Hermes cron registration, fallback job files, secret validation, cron report persistence.
- `routes.py` - Flask route composition.

## Cron Flow

`POST /api/cron/register` calls `register_all_crons()`.

When `hermes` is available, each job runs:

```bash
hermes cron create "<schedule>" --name "<name>" --prompt "<prompt>" --deliver "webhook:http://127.0.0.1:5050/api/cron/<endpoint>"
```

When unavailable, the job definition is written as JSON to `~/.hermes/cron/` or `data/hermes-cron/`.

Cron callbacks write `cron_reports` rows and return the generated brief, risk scan, or weekly report payload. If `CRON_SECRET` is set, callbacks must include the matching secret.

## Knowledge Flow

- Reads:
  - Hermes memory: `~/.hermes/memories/`
  - Hermes shared routing: `~/.hermes/skills/productivity/obsidian-shared-knowledge/references/cross-tool-routing.md`
  - Claude agents: `~/.claude/agents/`
  - Coordinator state: `~/company/.agent-coordinator/state.json`

- Writes:
  - Knowledge Hub exports Markdown to `~/Desktop/obsidian-inbox/`.
  - The user can move exported files into the Obsidian vault manually.

## Build

Frontend build command:

```bash
cd frontend
npm run build
```

Vite writes the production SPA to `static/app/`, which Flask serves under `/app/`.
