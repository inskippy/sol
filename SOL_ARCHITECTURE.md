# SOL — School of Life: Architecture Blueprint

## Vision

SOL is a personal operating system and ambient assistant. It is not a chatbot you open —
it reaches out to you. It knows your goals, your backlog, and your current focus. It nudges
you toward what matters, accepts freeform input via Telegram, and delegates executable tasks
to agents. The Obsidian vault is the source of truth. Claude API is the brain. The host
(an always-on NAS) runs SOL continuously.

---

## Current State (as of implementation start)

- Working CLI (`syllabus.py`) with:
  - Model toggle: Claude Sonnet / Llama 3.2 via `ACTIVE_MODEL` env var
  - Vault read/write via `_context.md` per project and `_global_context.md`
  - `<update_context>` and `<update_file>` XML tag parsing
  - Approval-gated file writes
  - Streaming responses
  - Safety guard: all writes sandboxed to `VAULT_PATH`
- Vault structure: `VAULT_PATH/projects/{project-name}/`
- Git repo initialized, `.env` secrets, `uv` for dependency management
- Host running, SSH accessible, always-on

---

## Target Architecture

```
┌─────────────────────────────────────────────────────┐
│                    HOST (NAS)                        │
│                                                     │
│  ┌─────────────┐    ┌──────────────────────────┐   │
│  │  Obsidian   │    │      SOL Python App       │   │
│  │    Vault    │◄───│                          │   │
│  │  (source    │    │  ┌────────┐ ┌─────────┐  │   │
│  │  of truth)  │    │  │ brain  │ │scheduler│  │   │
│  └─────────────┘    │  │(claude │ │ (cron)  │  │   │
│                     │  │  api)  │ └────┬────┘  │   │
│                     │  └───┬────┘      │        │   │
│                     │      │           │        │   │
│                     │  ┌───▼───────────▼──────┐ │   │
│                     │  │   Telegram Bot        │ │   │
│                     │  │  (push + receive)     │ │   │
│                     │  └──────────────────────┘ │   │
│                     └──────────────────────────┘   │
└─────────────────────────────────────────────────────┘
                              │
                    ┌─────────▼──────────┐
                    │    Your Phone       │
                    │  (Telegram app)     │
                    └────────────────────┘
```

---

## Vault Structure

```
VAULT_PATH/                          ← SOL subfolder in Obsidian vault
  _global_context.md                 ← cross-project memory, updated by SOL
  _sol_state.json                    ← SOL internal state (active focus, last nudge, etc.)

  projects/
    sol/                             ← SOL development project
      _context.md
      roadmap.md                     ← post-MVP feature checklist
      ARCHITECTURE.md                ← this document (copy here)

    arXiv-capstone/                  ← PRIMARY ACTIVE PROJECT
      _context.md
      milestones.md                  ← week-by-week submission targets
      tasks.md                       ← checkbox task list
      notes.md                       ← freeform intake/brain dump

    the-lab/                         ← backlog inbox
      _context.md
      backlog.md                     ← imported from existing Obsidian "The Lab"
      active.md                      ← items pulled into current focus

    kira/
      _context.md
      tasks.md

    coins/
      _context.md
      tasks.md

    ainskip-portfolio/
      _context.md
      tasks.md
```

---

## Module Breakdown

### 1. `brain.py` — LLM Interface
- Wraps Anthropic API + Ollama (existing model toggle, extended to `MODEL_CONFIGS` dict)
- Models: `haiku` (default), `sonnet` (planning), `llama` (free/offline)
- Exposes: `think(messages, model) -> str`

### 2. `vault.py` — Obsidian Read/Write
- All file I/O sandboxed to `VAULT_PATH`
- `read_context(project)`, `write_context(project, content)`
- `read_file(project, filename)`, `write_file(project, filename, content)`
- `read_all_contexts()` → full vault snapshot for nudge generation
- `list_projects()`, `load_project_tasks(project)`

### 3. `telegram_bot.py` — Push + Receive
- Outbound: `send_nudge(message)` → posts to your Telegram chat
- Inbound: webhook or polling handler for your replies
- Reply parsing: passes raw text to `brain.py` for intent extraction
- Intent types: `ADD_TASK`, `RESCHEDULE`, `MARK_DONE`, `BRAIN_DUMP`, `QUERY`
- Executes vault updates after parsing

### 4. `scheduler.py` — Cron Jobs
- `weekly_nudge()` — Monday 8am: reads vault, generates focus message, sends via Telegram
- `intake_absorb()` — daily: checks `notes.md` intake logs, absorbs into structured tasks
- `checkpoint()` — end of focus period: summarize progress, prep next focus
- Runs via `cron` on the host or `APScheduler` within the Python process

### 5. `cli.py` — Interactive Terminal (existing `syllabus.py`, refactored)
- Kept for desktop interactive sessions
- Now imports from `brain.py`, `vault.py` instead of inline logic
- `/model`, `/switch`, `/dump`, `/triage` commands

### 6. `state.py` — SOL Internal State
- Persisted to `_sol_state.json` in vault
- Tracks: `active_project`, `current_focus`, `last_nudge_date`, `nudge_count`, `pending_approvals`

---

## Primary Launch Use Case: arXiv Capstone

**Goal:** Turn 90-page capstone DOCX + prototype repo (KIRA) into a published arXiv preprint.

**SOL's role:**
- Maintain `arXiv-capstone/milestones.md` with week-by-week targets
- Send Monday nudge focused on this week's milestone
- Accept freeform updates ("finished the abstract, moved the deadline back a week")
- Track blockers and surface them in nudges

**Suggested milestone structure** (populate in `milestones.md`):
```
Week 1: Extract core contribution, define paper scope vs capstone scope
Week 2: Abstract + Introduction draft
Week 3: Related Work section
Week 4: Methodology section (from capstone Chapter 3)
Week 5: Results + Figures
Week 6: Discussion + Conclusion
Week 7: Internal review pass, format for arXiv (LaTeX or PDF)
Week 8: Submit
```

---

## Data Flow: Telegram Nudge Loop

```
Monday 8am cron
  → scheduler.weekly_nudge()
  → vault.read_all_contexts()
  → brain.think("generate nudge from context")
  → telegram_bot.send_nudge(message)
  → you reply: "push arxiv to week 3, add 'fix KIRA auth bug' to lab"
  → telegram_bot receives reply
  → brain.think("parse intent from reply")
  → returns structured intents
  → vault.write updates
  → telegram_bot.send_nudge("Got it — updated.")
```

---

## Model Strategy

| Task | Model | Reason |
|---|---|---|
| Weekly nudge generation | `haiku` | Simple summarization, cheap |
| Intent parsing from reply | `haiku` | Structured extraction, fast |
| Brain dump → structured tasks | `sonnet` | Needs reasoning quality |
| 8-week syllabus generation | `sonnet` | Complex planning |
| Offline / free queries | `llama` | No API cost |

### Ollama: Deferred-to-Laptop Pattern

The host cannot run Ollama (no GPU, inference would take minutes). Instead, SOL running
on the host calls Ollama on the dev laptop over a direct ethernet link when it's on.

```env
OLLAMA_HOST=http://<dev-laptop-lan-ip>:11434   # dev laptop IP on the direct LAN link
```

```python
# brain.py — fallback logic
try:
    response = ollama_client.chat.completions.create(model="llama3.2", ...)
except Exception:
    # laptop off or unreachable — fall back to haiku silently
    response = anthropic_client.messages.create(model="claude-haiku-4-5-20251001", ...)
```

Llama is opportunistic — used when the laptop is on, silently falls back to Haiku
(cheap, fast) when it's not. Never blocks SOL from functioning.

---

## Focus Pivot & Drift Detection

SOL supports freeform focus pivots at any time. When you say "switching to project Y,"
SOL moves the current focus to a deferred list with a drift threshold. If you go too
long without returning, it surfaces a gentle nudge.

### State schema (`_sol_state.json`)

```json
{
  "active_focus": "project-y",
  "focus_set_date": "2026-07-18",
  "deferred": [
    {
      "project": "arXiv-capstone",
      "deferred_date": "2026-07-18",
      "reason": "pivoting to project-y",
      "drift_threshold_weeks": 4,
      "drift_message": "It's been a while since you touched the arXiv paper — still shelved, or worth pulling back in?"
    }
  ]
}
```

### Scheduler drift check (weekly, runs alongside nudge)

```python
def check_drift(state):
    for item in state["deferred"]:
        weeks_deferred = (today - item["deferred_date"]).days // 7
        if weeks_deferred >= item["drift_threshold_weeks"]:
            send_nudge(item["drift_message"])
            item["drift_threshold_weeks"] += 2  # back off cadence if ignored
```

### Conversation flow

```
You: "switching focus to project-y, put arXiv on the back burner"
SOL: "Got it — project-y is your focus. arXiv shelved. I'll check in after 4 weeks."

[4 weeks later, alongside Monday nudge]
SOL: "It's been 4 weeks since you shelved the arXiv paper — still on hold, or worth pulling back in?"

You: "yeah still shelved"
SOL: "Noted — I'll check back in another month."

You: "actually let's bring it back"
SOL: "arXiv-capstone back as co-focus. Current milestone: Abstract draft. Want me to reprioritize this week's tasks?"
```

Drift messages are conversational, not nagging. Threshold backs off if ignored.

---

## Hosting Deployment

```bash
# Host runs Debian-based DSM with Docker support
# Recommended: Docker container for SOL

Dockerfile:
  python:3.11-slim base
  install uv + dependencies
  mount vault as volume (already on NAS)
  run: python scheduler.py (blocking, APScheduler loop)
  expose: nothing (outbound only via Telegram + Anthropic API)

# Alt: run directly in DSM Task Scheduler (cron) if Docker feels heavy for MVP
```

---

## Tech Stack

| Component | Technology |
|---|---|
| Language | Python 3.11+ |
| Package mgmt | uv |
| LLM (cloud) | Anthropic API (claude-haiku-4-5, claude-sonnet-4) |
| LLM (local) | Ollama + Llama 3.2 |
| Vault | Obsidian markdown files |
| Telegram | `python-telegram-bot` library |
| Scheduling | `APScheduler` or DSM Task Scheduler |
| Hosting | Host (NAS) via Docker |
| Secrets | `.env` + `python-dotenv` |
| Version control | Git |

---

## Environment Variables

```env
# LLM
ANTHROPIC_API_KEY=sk-ant-...
ACTIVE_MODEL=haiku               # haiku | sonnet | llama

# Vault
VAULT_PATH=/path/to/vault/SOL

# Telegram
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...             # your personal chat ID with the bot

# Ollama (optional — laptop must be on and reachable)
OLLAMA_HOST=http://<dev-laptop-lan-ip>:11434   # dev laptop on the direct LAN link

# Scheduling
NUDGE_DAY=monday
NUDGE_TIME=08:00
TZ=America/Los_Angeles
```

---

## Implementation Phases

### Phase 1 — Telegram MVP (immediate)
- [ ] Create Telegram bot via @BotFather, get token
- [ ] Get your chat ID
- [ ] Implement `telegram_bot.py` — outbound send only
- [ ] Implement `scheduler.py` — weekly nudge, reads vault, sends message
- [ ] Wire into existing `vault.py` (refactor from `syllabus.py`)
- [ ] Run locally first, then deploy to the host
- [ ] Create `arXiv-capstone` project folder + milestones

### Phase 2 — Two-way conversation
- [ ] Add inbound handler to `telegram_bot.py`
- [ ] Implement intent parsing in `brain.py`
- [ ] Connect intents → vault writes
- [ ] Add `state.py` for tracking nudge state

### Phase 3 — Lab backlog absorption
- [ ] Import existing "The Lab" Obsidian content into `the-lab/backlog.md`
- [ ] Build triage prompt: reads backlog, suggests active vs defer vs drop
- [ ] Weekly: surface one lab item alongside arXiv nudge

### Phase 4 — Agent delegation
- [ ] Identify "delegatable" task types (research, code, drafting)
- [ ] Wire coding tasks → Claude Code via API
- [ ] Wire calendar tasks → Google Calendar API
- [ ] MCP server integration (mcp-obsidian for richer vault access)
