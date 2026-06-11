# AGENTS.md

## Cursor Cloud specific instructions

### Product overview

CEO Console is a local-first Flask + Vue 3 SPA for a one-person-company AI operating cockpit. One Python process (`server.py`) serves the REST API, legacy HTML dashboard, and built SPA assets. SQLite lives at `data/ceo_console.db` (auto-created).

### Services

| Service | Command | URL |
|---------|---------|-----|
| Flask backend (required) | `python3 server.py` (from repo root) | `http://127.0.0.1:5050` |
| Vue dev server (SPA development) | `cd frontend && npm run dev` | `http://localhost:5173/app/` |
| Built SPA (served by Flask) | `cd frontend && npm run build` then run backend | `http://127.0.0.1:5050/app/` |
| Legacy dashboard | backend only | `http://127.0.0.1:5050/` or `/legacy` |

Run backend and frontend in separate terminals (or tmux sessions). The Vite dev server proxies `/api` to `http://127.0.0.1:5050`.

### PATH note

`pip install --user` places `pytest`, `flask`, and `playwright` under `~/.local/bin`. If those commands are not found, run:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

### Vite localhost vs 127.0.0.1

In this Cloud VM, Vite binds to `localhost` (IPv6). Use `http://localhost:5173/app/` for the dev UI. `http://127.0.0.1:5173` may refuse connections even when Vite is healthy.

### Testing

See `README.md` and `.github/workflows/tests.yml`:

```bash
export PATH="$HOME/.local/bin:$PATH"
python3 -m pip install -r requirements-dev.txt
python3 -m playwright install chromium   # first-time only; large download
python3 -m pytest -q
```

72+ unit/integration tests pass in a clean setup. Two Playwright E2E tests in `tests/test_dashboard_e2e.py` may fail when `#colTodo` stays hidden in the legacy dashboard task-center view; this is a known UI visibility issue, not an environment problem.

### Lint / typecheck

No repo-wide Python linter is configured. Frontend typecheck runs as part of `npm run build` (`vue-tsc -b`).

### Optional external dependencies

Not required for API/UI smoke tests. Needed only for real project ops and AI dispatch:

- Company directory: `~/company` (or fallbacks documented in `README.md`)
- `~/ai-team-template/初始化脚本/pm` for project lifecycle
- ACP scripts and AI tool CLIs under the company directory
- API keys: `CEO_CONSOLE_GEMINI_API_KEY`, `CEO_CONSOLE_DEEPSEEK_API_KEY`, etc.

### macOS launchd scripts

`scripts/install-launchd.sh` is macOS-only (`launchctl`). Do not use on Linux Cloud VMs.
