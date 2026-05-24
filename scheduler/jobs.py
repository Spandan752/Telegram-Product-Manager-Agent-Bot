"""
APScheduler jobs for proactive agent behaviour.
 
Jobs:
  1. morning_standup_ping — DMs each team member asking for their update
  2. evening_digest — posts a full status summary to the group
  3. overdue_followup — DMs assignees of overdue tasks
  4. blocked_task_alert — posts blocked tasks to the group if any exist
 
All jobs call run_agent() with a synthetic message so the LLM decides
exactly what to say — the scheduler just decides *when* and *who*.
"""
import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from config import get_settings
from db.database import get_db
from db.crud import list_members, list_overdue_tasks, get_member_by_username, list_tasks
from db.models import TaskStatus

settings = get_settings()

_scheduler: AsyncIOScheduler | None = None


# Helper functions

def _get_event_loop():
    try:
        return asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return loop
    
async def _send(chat_id: str, text: str) -> None:
    """Send a plain message without going through the agent."""
    from bot.telegram import send_message
    try:
        await send_message(chat_id, text)
    except Exception as e:
        raise RuntimeError(f"Failed to send message to {chat_id}: {e}")
 
async def _agent(chat_id: str, prompt: str, sender: str = "Scheduler") -> str:
    """Run the agent with a synthetic prompt and return the reply."""
    from agent.graph import run_agent
    try:
        return await run_agent(
            chat_id=chat_id,
            user_message=prompt,
            sender_name=sender,
        )
    except Exception as e:
        raise RuntimeError(f"Agent error in scheduled job: {e}")


# Job 1: Morning standup ping

async def _morning_standup_ping():
    """
    Every morning: DM each active team member asking for their update.
    Then post a prompt to the group to kick off the standup.
    """
    group_id = settings.telegram_group_id

    # get list of active team members from db
    with get_db() as db:
        members = list_members(db, group_id)
        member_data = [
            (m.telegram_user_id, m.display(), m.full_name or m.display())
            for m in members
        ]

    if not member_data:
        return "No team members found, skipping standup ping"
        
    # DM each member asking for their update
    for user_id, display, name in member_data:
        first_name = name.split()[0] if name else display
        dm_text = (
        f"Hey {first_name} Quick standup check-in:\n\n"
        f"• What did you work on yesterday?\n"
        f"• What are you focusing on today?\n"
        f"• Any blockers?\n\n"
        f"Reply here and I'll include it in the team update."
        )
        await _send(user_id, dm_text)

    # Post a prompt to the group to kick off the standup
    group_reply = await _agent(
        group_id,
        "It's standup time. Post a friendly message to the group kicking off the daily standup "
        "and reminding everyone you've DM'd them for updates.",
        sender="Scheduler"
    )
    if group_reply:
        await _send(group_id, group_reply)


# Job 2: Evening update

async def _evening_update():
    """
    Every evening: post a full status digest to the group.
    Uses generate_standup_summary tool via the agent.
    """
    group_id = settings.telegram_group_id

    reply = await _agent(
        group_id,
        "Generate the end-of-day status digest for the team. "
        "Use the standup summary tool and post it with a brief intro.",
        sender="Scheduler"
    )
    if reply:
        await _send(group_id, reply)
        

# Job 3: Overdue task follow-up

async def _overdue_followup():
    """
    Every afternoon: DM assignees of overdue tasks.
    Also post a summary of overdue items to the group if any exist.
    """
    group_id = settings.telegram_group_id

    with get_db() as db:
        overdue_tasks = list_overdue_tasks(db, group_id)
        overdue_data = [
            {
                "id": t.id,
                "title": t.title,
                "due_date": t.due_date,
                "assignee_username": t.assignee_username,
                "assignee_name": t.assignee_name,
                "short": t.short_str(),
            }
            for t in overdue_tasks
        ]

    if not overdue_data:
        return "No overdue tasks, skipping follow-up"
    
    # DM assignees of overdue tasks
    notified = set()
    with get_db() as db:
        for task in overdue_data:
            username = task["assignee_username"]
            if not username or username in notified:
                continue
 
            member = get_member_by_username(db, group_id, username)
            if not member:
                continue
 
            first_name = (member.full_name or username).split()[0]
            dm_text = (
                f"Hey {first_name} Just a heads-up — task #{task['id']} is overdue:\n\n"
                f"*{task['title']}*\n"
                f"Due: {task['due_date']}\n\n"
                f"Can you give me a quick update? Still in progress, blocked, or done?"
            )
            await _send(member.telegram_user_id, dm_text)
            notified.add(username)

    # Post a summary of overdue items to the group
    overdue_list = "\n".join(f"  • {t['short']}" for t in overdue_data)
    group_msg = (
        f"*Overdue Tasks ({len(overdue_data)})*\n\n"
        f"{overdue_list}\n\n"
        f"I've reached out to the assignees directly. "
        f"Let me know if priorities have changed."
    )
    await _send(group_id, group_msg)


# Job 4: Blocked task alert

async def _blocked_task_alert():
    """
    Twice daily: if any tasks are blocked, surface them to the group.
    Only posts if there are actually blocked tasks.
    """
    group_id = settings.telegram_group_id

    with get_db() as db:
        blocked_tasks = list_tasks(db, group_id, status=TaskStatus.BLOCKED)
        blocked_data = [
            f"#{t.id} — {t.title} ({t.assignee_username or t.assignee_name or 'Unassigned'})"
            + (f"\n    ↳ {t.blocker}" if t.blocker else "")
            for t in blocked_tasks
        ]

    if not blocked_data:
        return "No blocked tasks, skipping alert"
    
    msg = (
        f"🚧 *Blocked Tasks ({len(blocked_data)}) — needs attention*\n\n"
        + "\n".join(f"• {s}" for s in blocked_data)
        + "\n\nCan someone help unblock these?"
    )
    await _send(group_id, msg)


# Sync wrappers to call async jobs from APScheduler

def _run(coro):
    """Run an async job from APScheduler's sync context."""
    loop = _get_event_loop()
    if loop.is_running():
        asyncio.ensure_future(coro)
    else:
        loop.run_until_complete(coro)
 
 
def job_standup(): _run(_morning_standup_ping())
def job_digest(): _run(_evening_update())
def job_overdue(): _run(_overdue_followup())
def job_blocked(): _run(_blocked_task_alert())


# Scheduler lifecycle

def start_scheduler() -> None:
    global _scheduler

    _scheduler = AsyncIOScheduler(Timezone="UTC")

    # Morning standup ping — weekdays only
    _scheduler.add_job(
        job_standup,
        CronTrigger(
            day_of_week="mon-fri",
            hour=settings.standup_hour,
            minute=settings.standup_minute,
        ),
        id="morning_standup",
        name="Morning standup ping",
        replace_existing=True,
    )

    # Evening digest — every day
    _scheduler.add_job(
        job_digest,
        CronTrigger(
            hour=settings.digest_hour,
            minute=settings.digest_minute,
        ),
        id="evening_digest",
        name="Evening status digest",
        replace_existing=True,
    )

    # Overdue follow-up — weekday afternoons
    _scheduler.add_job(
        job_overdue,
        CronTrigger(
            day_of_week="mon-fri",
            hour=settings.followup_hour,
            minute=settings.followup_minute,
        ),
        id="overdue_followup",
        name="Overdue task follow-up",
        replace_existing=True,
    )
 
    # Blocked task alert — weekdays, morning + afternoon
    _scheduler.add_job(
        job_blocked,
        CronTrigger(
            day_of_week="mon-fri",
            hour="10,15",
            minute=0,
        ),
        id="blocked_alert",
        name="Blocked task alert",
        replace_existing=True,
    )

    _scheduler.start()
    

def stop_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)