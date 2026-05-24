# Alex — Agentic PM for Telegram

An AI Product Manager that lives inside your Telegram group. Tracks tasks, logs decisions, runs standups, and proactively follows up with your team — without anyone having to ask.

---

## What's implemented

| Requirement | Status | How |
|---|---|---|
| Lives in Telegram group | ✅ | python-telegram-bot webhook, always-on via FastAPI |
| Telegram-only interface | ✅ | All I/O via group messages + DMs. No web UI. |
| Manage tasks | ✅ | Create, assign, update, close — 10 LangChain tools backed by SQLite |
| Actively pull updates | ✅ | APScheduler DMs each team member every morning for standup |
| Provide status regularly | ✅ | Evening digest + overdue alerts + blocked task pings, all scheduled |

### What's stubbed / not implemented
- **No OAuth / per-user auth** — the bot trusts all group members equally. A production version would add role-based access (e.g. only leads can close tasks).
- **SQLite only** — sufficient for a demo. Swap `DATABASE_URL` for Postgres with zero code changes (SQLAlchemy handles it).
- **No message queue** — high-volume groups could hit rate limits. Production would add a queue (Celery + Redis) in front of the agent.
- **Webhook only, no polling fallback** — requires a public HTTPS URL. For local dev, use ngrok.

---

## Tech stack

| Layer | Tool | Why |
|---|---|---|
| Bot interface | python-telegram-bot 21 | Native async, webhook support, well-maintained |
| Web server | FastAPI + uvicorn | Async, lifespan hooks, minimal boilerplate |
| Agent framework | LangGraph | Graph-based flow handles multi-step tool loops cleanly |
| LLM | Google Gemini 2.5 Flash | Best-in-class for nuanced judgment (when to act, when to stay quiet) |
| Tools | LangChain `@tool` | Clean schema → docstring pattern Claude reads as instructions |
| Database | SQLAlchemy + SQLite | Persistent across restarts, zero infra for demo |
| Scheduler | APScheduler | In-process cron, no extra infra needed |

---

## Project layout

```
pm-agent/
├── main.py                  ← FastAPI app, webhook endpoint, startup/shutdown
├── config.py                ← All settings from .env (pydantic-settings)
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
│
├── prompts/
│   └── system.md            
│
├── db/
│   ├── models.py            ← Task, Decision, SprintGoal, ChatMessage, TeamMember
│   ├── database.py          ← Engine + get_db() context manager
│   └── crud.py              ← All DB reads/writes in one place
│
├── agent/
│   ├── tools.py             ← 10 LangChain tools (create_task, log_decision, ...)
│   └── graph.py             ← LangGraph: build_context → call_llm → run_tools loop
│
├── bot/
│   ├── telegram.py          ← Application singleton, send helpers
│   └── handlers.py          ← Command + message handlers
│
└── scheduler/
    └── jobs.py              ← 4 APScheduler cron jobs
```

---

## Quickstart

### 1. Create the Telegram bot

1. Message **@BotFather** → `/newbot` → copy the token
2. `/setprivacy` → select your bot → **Disable** (so it reads all group messages)
3. Add the bot to your group and make it **Admin**
4. Find your group's chat ID: add **@userinfobot** to the group, it prints the ID (negative number like `-1001234567890`)

### 2. Get a public HTTPS URL

Telegram requires HTTPS for webhooks. For local dev:
```bash
ngrok http 8000
# copy the https://xxxx.ngrok.io URL
```
For production: deploy to Railway, Render, Fly.io, or any VPS with a domain + SSL.

### 3. Configure

```bash
cp .env.example .env
# Fill in all values
```

```env
TELEGRAM_BOT_TOKEN=123456789:ABCdef...
TELEGRAM_GROUP_ID=-1001234567890
BOT_USERNAME=AlexpmBot             # without @
GOOGLE_API_KEY="your_api_key"
WEBHOOK_BASE_URL=https://xxxx.ngrok.io
DATABASE_URL=sqlite:///./data/pm_agent.db
```

### 4. Run

**With Docker (recommended):**
```bash
mkdir -p data
docker compose up --build
```

**Without Docker:**
```bash
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### 5. Verify

```bash
curl http://localhost:8000/health
# {"status":"ok","agent":"Aria"}
```

Then send `/start` to the Telegram group. Aria should reply.

---

## Commands

| Command | What happens |
|---|---|
| `/start` | Introduction and command list |
| `/tasks` | All open + in-progress tasks |
| `/decisions` | Decision log |
| `/standup` | Full status summary |
| `/sprint <goal>` | Set the sprint goal |
| `/help` | Same as /start |

**Natural language** (mention the bot in the group):
```
@AlexpmBot track that Pooja needs to finish the API docs by Friday
@AlexpmBot mark task 3 as done
@AlexpmBot we decided to go with Postgres — log that
@AlexpmBot what's blocking the team right now?
```

---

## Scheduled jobs (UTC)

| Job | Schedule | What it does |
|---|---|---|
| Morning standup ping | Mon–Fri 10:00 | DMs each team member for their update; posts group kickoff |
| Evening digest | Daily 18:00 | Posts full status summary to the group |
| Overdue follow-up | Mon–Fri 16:00 | DMs assignees of overdue tasks; posts group alert |
| Blocked task alert | Mon–Fri 10:00 & 15:00 | Posts blocked tasks to group if any exist |

All times configurable via `.env` (`STANDUP_HOUR`, `DIGEST_HOUR`, `FOLLOWUP_HOUR`).

---

## Design decisions and tradeoffs

### Why LangGraph over a plain LangChain agent?
LangGraph gives explicit control over the reasoning loop. I can add nodes (e.g. a "check if response is appropriate for group" node), add memory, or branch on state — without restructuring the whole agent. A plain `AgentExecutor` would make that harder.

### Why does the agent only respond to mentions/replies in group chats?
A PM that replies to every message is a PM that gets muted. The agent stays quiet until addressed, but acts proactively on its own schedule via the scheduler. This is the right default — less noise, more trust.

### Why is the system prompt a `.md` file, not a Python string?
Tone and behaviour need iteration independent of code. A PM or non-engineer should be able to adjust how Aria talks without touching Python. The file is read at startup, so changes take effect on redeploy.

### Why SQLite and not Postgres?
Zero infra for a demo — no Docker Compose database service, no connection pool config, no migration headaches. The `DATABASE_URL` env var and SQLAlchemy mean switching to Postgres is a one-line change: `postgresql://user:pass@host/db`.

### What I'd build next
1. **Standup response collection** — when a member replies to the morning DM, parse their update and post a consolidated standup to the group
2. **Task mention parsing** — detect `@username` in group messages and auto-assign tasks
3. **Weekly retrospective** — Friday EOD: what got done, what slipped, what blocked the team
4. **Postgres + Alembic migrations** — for multi-group production use
5. **Rate limiting** — prevent the agent from spamming if something goes wrong in the scheduler

---

## Running tests

```bash
# Smoke test — no API keys needed
TELEGRAM_BOT_TOKEN=fake TELEGRAM_GROUP_ID=-100 \
BOT_USERNAME=AlexBot GOOGLE_API_KEY=fake \
WEBHOOK_BASE_URL=https://example.com \
python -m pytest tests/ -v   # (tests mirror the smoke tests run during build)
```