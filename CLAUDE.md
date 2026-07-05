# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

SOL (School of Life) is a personal operating system and ambient assistant. It is not a chatbot you open — it reaches out to you. It knows your goals, your backlog, and your current focus. It nudges you toward what matters, accepts freeform input via Telegram, and delegates executable tasks to agents. The Obsidian vault is the source of truth. Claude API is the brain. The host (an always-on NAS) runs SOL continuously.

Full system blueprint: `SOL_ARCHITECTURE.md`

## Obsidian Vault

The live SOL vault path is set via the `VAULT_PATH` env var (see `.env.example`). Read access is granted in `.claude/settings.json` (local, gitignored). Structure:

```
SOL/
  _global_context.md          # cross-project running summary
  _sol_state.json             # SOL internal state (active focus, nudge tracking, deferred)
  projects/
    <project-name>/
      _context.md             # per-project running summary (auto-updated by the app)
      *.md                    # task lists, roadmaps, etc. (injected into LLM context)
```

Projects: `sol`, `arXiv-capstone` (primary), `the-lab`, `kira`, `coins`, `ainskip-portfolio`

## Setup

Dependencies managed with `uv`. Copy `.env.example` to `.env`:

```env
ANTHROPIC_API_KEY=sk-ant-...
ACTIVE_MODEL=haiku               # haiku | sonnet | llama
VAULT_PATH=/path/to/Obsidian/CoreVault/SOL

TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...

OLLAMA_HOST=http://<dev-laptop-lan-ip>:11434   # dev laptop, direct LAN link — optional

NUDGE_DAY=monday
NUDGE_TIME=08:00
TZ=America/Toronto
```

```bash
uv sync
```

## Running (current CLI)

```bash
uv run python syllabus.py <project-name>   # focus on a project
uv run python syllabus.py                  # interactive project selection
```

In-session: `quit` to exit, `switch <project>` to change focus.

## Target Module Architecture

`syllabus.py` is the working foundation. The refactor splits it into:

| File | Responsibility |
|---|---|
| `vault.py` | All Obsidian file I/O, sandboxed to `VAULT_PATH` |
| `brain.py` | LLM interface — wraps Anthropic + Ollama with model toggle |
| `telegram_bot.py` | Outbound push + inbound reply handler |
| `scheduler.py` | Cron jobs: weekly nudge, intake absorption, drift check |
| `cli.py` | Refactored `syllabus.py` — imports from above modules |
| `state.py` | Reads/writes `_sol_state.json` for focus tracking |

Build order: `vault.py` → `brain.py` → `telegram_bot.py` → `scheduler.py` → `cli.py`

### Model strategy

- `haiku` — weekly nudge generation, intent parsing (cheap, fast)
- `sonnet` — brain dump → structured tasks, syllabus generation (needs reasoning)
- `llama` — offline/free; runs on the dev laptop, called over the direct LAN link (`OLLAMA_HOST`). The host has no GPU. If the laptop is unreachable, fall back to haiku silently — never block SOL.

## User Preferences

- Review diffs before they're written. No autonomous file writes without approval.
- Implement one module at a time. Show the file, wait for confirmation, then write it.
- Git commit after each approved module with a clean message.
- Test Telegram outbound (`send_nudge("test")`) before wiring the scheduler.
- All secrets in `.env`, never hardcoded.

## Deployment: Dev laptop → Host

**Current environment:** Dev laptop (Windows 11, development)
**Target host:** Always-on NAS, SSH accessible, Docker-capable (Debian-based DSM)

### Vault access gotcha

The Obsidian vault lives on the **dev laptop**, not the host. Syncthing syncs between the laptop and mobile via a `Synced/` subfolder inside the CoreVault. When SOL deploys to the host it needs vault access — options ranked by preference:

1. **Add the host as a Syncthing peer** (recommended) — vault replicated to the host, SOL reads/writes locally, no laptop dependency at runtime.
2. **SMB/NFS mount from the laptop** — simpler but SOL breaks if the laptop is off.

Also note: only paths inside `Synced/` propagate to mobile. Verify that `projects/<name>/` paths are inside `Synced/` if phone access to SOL updates matters.

### Deployment path

**Phase 1 (local):** Run and validate on the dev laptop first. SOL doesn't need to be always-on yet.

**Phase 2 (host via SSH):**
```bash
# Prerequisite: host added as Syncthing peer, vault path confirmed
ssh sol-host
git clone <repo> ~/sol
cd ~/sol && pip install uv && uv sync
cp .env.example .env && nano .env   # fill in secrets + correct VAULT_PATH for the host
uv run python scheduler.py          # test manually before daemonizing
```

**Phase 3 (Docker on the host):**
```dockerfile
FROM python:3.11-slim
WORKDIR /app
RUN pip install uv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen
COPY . .
CMD ["uv", "run", "python", "scheduler.py"]
```
Mount the Syncthing-replicated vault as a volume:
```bash
docker run -d \
  --name sol \
  --restart unless-stopped \
  -v /volume1/syncthing/CoreVault/SOL:/vault \  # adjust to actual path on the host
  -e VAULT_PATH=/vault \
  --env-file .env \
  sol-image
```

**Phase 4 (CI/CD via GitHub Actions):**
Goal: push to `main` → tests run → auto-deploy to the host.

```yaml
# .github/workflows/deploy.yml (scaffold — implement when ready)
on:
  push:
    branches: [main]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pip install uv && uv sync && uv run pytest
  deploy:
    needs: test
    runs-on: ubuntu-latest
    steps:
      - name: Deploy to host
        run: |
          ssh -i ${{ secrets.SOL_HOST_KEY }} user@sol-host \
            "cd ~/sol && git pull && docker compose restart"
```

Prerequisites for CI/CD:
- Host reachable from GitHub Actions (Tailscale tunnel recommended over port forward)
- `SOL_HOST_KEY` SSH private key in GitHub repo secrets
- `docker-compose.yml` in repo
- Start with `test` job only — add `deploy` once tests are stable and you're comfortable with the pattern

## MCP Obsidian Integration (Phase 4 goal)

Replacing direct file I/O in `vault.py` with an MCP Obsidian server is a first-class goal. It gives richer vault access (backlinks, search, graph queries) and eliminates the Syncthing/path complexity for Claude Code sessions — the MCP server handles vault access directly. When ready, wire `vault.py` to call MCP tools instead of reading files directly; the rest of the app stays unchanged.

## Architecture Notes

### Vault safety model

Every vault operation must pass a path-prefix check against `VAULT_PATH` before anything happens. Beyond that, approval requirements differ by operation:

| Operation | Behaviour |
|---|---|
| New file (path doesn't exist) | Path check → auto-apply |
| `_context.md` overwrite | Path check → write immediately → store original in session memory → show result → offer `r` to revert |
| Any other file overwrite | Path check → show diff → explicit `y/n` before writing |
| Deletion | Path check → show what will be deleted → explicit `y/n` with warning |

**`_context.md` revert detail:** the pre-write content is kept in a dict keyed by project name for the duration of the conversation. If the user types `r`, `vault.py` writes the original back and logs a `reverted` entry. Memory is per-session only — no persistent undo beyond the log.

**Modification log (`_sol_log.md`):** append-only file at vault root. One line per operation:
```
2026-07-04 14:23 | updated  | projects/sol/_context.md
2026-07-04 14:31 | created  | projects/arXiv-capstone/milestones.md
2026-07-04 14:45 | reverted | projects/sol/_context.md
2026-07-04 14:50 | deleted  | projects/old-project/_context.md
```
Log is intentionally low-signal — timestamps, operation type, relative path. Not a diff store. Implement in `vault.py` as a single `_log_operation(op, path)` helper called by every write/delete function.

### Other notes

- `_sol_state.json` tracks `active_focus`, `deferred` list with `drift_threshold_weeks`. Scheduler checks weekly and backs off cadence if nudges are ignored.
- Ollama is opportunistic: if `OLLAMA_HOST` is unreachable, fall back to haiku silently.
