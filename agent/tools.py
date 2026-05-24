from langchain_core.tools import tool
from typing import Optional
from datetime import datetime, timezone
from db.crud import create_task, get_task, list_tasks, update_task_status, list_overdue_tasks, update_task_fields, log_decisions, list_decisions, set_sprint_goal, get_sprint_goal, list_members
from db.database import get_db
from db.models import TaskStatus, TaskPriority

_CHAT_ID: str = ""

def set_chat_id(chat_id: str) -> None:
    """Called by the agent graph before each run to scope tools to the right chat."""
    global _CHAT_ID
    _CHAT_ID = chat_id


# Task tools

@tool
def create_task_tool(
    title: str,
    assignee_username: Optional[str] = None,
    assignee_name: Optional[str] = None,
    priority: str = "Medium",
    due_date: Optional[str] = None,
    description: Optional[str] = None
) -> str:
    """
    Create a new task for the team.
    Use this whenever the conversation identifies work that needs to be done.
    - title: short description e.g. 'Write API docs'
    - assignee_username: Telegram @username of the person
    - assignee_name: full name if username is unknown
    - priority: one of Critical / High / Medium / Low
    - due_date: ISO date string e.g. '2025-06-15', or omit if unknown
    - description: optional longer context
    Always announce the created task to the group after calling this.
    """
    try: 
        p = TaskPriority(priority)
    except ValueError:
        p = TaskPriority.MEDIUM

    with get_db() as db:
        task = create_task(
            db, _CHAT_ID,
            title=title,
            assignee_username=assignee_username,
            assignee_name=assignee_name,
            priority=p,
            due_date=due_date,
            description=description,
        )
        return (
            f"Task #{task.id} created\n"
            f"  Title:    {task.title}\n"
            f"  Assignee: {task.assignee_username or task.assignee_name or 'Unassigned'}\n"
            f"  Priority: {task.priority.value}\n"
            f"  Due:      {task.due_date or '—'}"
        )
    

@tool
def list_tasks_tool(
    status: Optional[str] = None,
    assignee_username: Optional[str] = None
) -> str:
    """
    List tasks for this group.
    - status: filter by Open / In Progress / Blocked / Done / Cancelled. Omit for all.
    - assignee_username: filter to one person's tasks (without @). Omit for everyone.
    """
    status_enum = None
    if status:
        try:
            status_enum = TaskStatus(status)
        except ValueError:
            return f"Unknown status '{status}'. Use: Open, In Progress, Blocked, Done, Cancelled."
 
    with get_db() as db:
        tasks = list_tasks(db, _CHAT_ID, status=status_enum, assignee_username=assignee_username)
        if not tasks:
            label = f"No {status or ''} tasks found."
            return label.strip()
        lines = [f"{'Status filter: ' + status if status else 'All tasks'} ({len(tasks)})\n"]
        for t in tasks:
            lines.append(t.short_str())
    return "\n".join(lines)


@tool
def update_task_status_tool(task_id: int, status: str) -> str:
    """
    Update the status of an existing task.
    - task_id: the numeric ID shown in task listings
    - status: one of Open / In Progress / Blocked / Done / Cancelled
    Use this when someone says a task is finished, blocked, or being worked on.
    """
    try:
        status_enum = TaskStatus(status)
    except ValueError:
        return f"Unknown status '{status}'. Use: Open, In Progress, Blocked, Done, Cancelled."
 
    with get_db() as db:
        task = update_task_status(db, _CHAT_ID, task_id, status_enum)
        if not task:
            return f"Task #{task_id} not found."
        return f"Task #{task_id} updated to '{task.status.value}' ✅  — {task.title}"
 

@tool
def update_task_tool(
    task_id: int,
    assignee_username: Optional[str] = None,
    assignee_name: Optional[str] = None,
    priority: Optional[str] = None,
    due_date: Optional[str] = None,
    blocker: Optional[str] = None,
) -> str:
    """
    Update fields of an existing task (reassign, reprioritise, set due date, note a blocker).
    Only pass the fields you want to change.
    - task_id: numeric task ID
    - assignee_username: new Telegram username (without @)
    - priority: Critical / High / Medium / Low
    - due_date: ISO date e.g. '2025-06-20'
    - blocker: description of what's blocking this task
    """
    kwargs = {}
    if assignee_username:
        kwargs["assignee_username"] = assignee_username.lstrip("@")
    if assignee_name:
        kwargs["assignee_name"] = assignee_name
    if priority:
        try:
            kwargs["priority"] = TaskPriority(priority)
        except ValueError:
            return f"Unknown priority '{priority}'."
    if due_date:
        kwargs["due_date"] = due_date
    if blocker is not None:
        kwargs["blocker"] = blocker
 
    with get_db() as db:
        task = update_task_fields(db, _CHAT_ID, task_id, **kwargs)
        if not task:
            return f"Task #{task_id} not found."
        return f"Task #{task_id} updated ✅\n{task.short_str()}"
    


# Decision tools

@tool
def log_decision_tool(
    summary: str,
    owner: Optional[str] = None
) -> str:
    """
    Record a decision.
    Call this whenever the team agrees on something that should be on record.
    - summary: one sentence e.g. 'We will use Postgres instead of MongoDB'
    - rationale: why this decision was made
    - owner: person or role accountable for this decision
    """
    with get_db() as db:
        d = log_decisions(db, _CHAT_ID, summary=summary, owner=owner)
        return (
            f"Decision #{d.id} logged\n"
            f"  {d.summary}\n"
            f"  Owner: {d.owner or '—'}"
        )
    

@tool
def list_decisions_tool(limit: int = 10) -> str:
    """
    List recently logged decisions for this group.
    - limit: how many to return (default 10, max 20)
    """
    with get_db() as db:
        decisions =  list_decisions(db, _CHAT_ID, limit=min(limit, 20))
        if not decisions:
            return "No decisions logged yet."
        
        lines = [f"Recent decisions ({len(decisions)})\n"]
        for d in decisions:
            lines.append(d.short_str())
    return "\n".join(lines)
    


# Sprint tools

@tool
def set_sprint_goal_tool(goal: str) -> str:
    """
    Set or update the current sprint goal for this group.
    Call this when the team defines or changes their sprint focus.
    - goal: the sprint goal in plain English
    """
    with get_db() as db:
        sg = set_sprint_goal(db, _CHAT_ID, goal)
        return f"Sprint goal set {sg.goal}"
    

@tool
def get_sprint_goal_tool() -> str:
    """
    Get the current sprint goal. Call before generating summaries or standups.
    """
    with get_db() as db:
        sg = get_sprint_goal(db, _CHAT_ID)
        goal = sg.goal if sg else None
    if not goal:
        return "No sprint goal set yet. Use /sprint <goal> to set one."
    return f"Current sprint goal\n  {goal}"


# Summary tool

@tool
def generate_summary_tool() -> str:
    """
    Generate a standup / status report for the group.
    Pulls live data: sprint goal, open/in-progress/blocked tasks, recent decisions.
    Call this when someone asks for a standup, status update, or daily summary.
    """
    with get_db() as db:
        sg = get_sprint_goal(db, _CHAT_ID)
        open_task = list_tasks(db, _CHAT_ID, status=TaskStatus.OPEN)
        prog_task = list_tasks(db, _CHAT_ID, status=TaskStatus.IN_PROGRESS)
        blocked   = list_tasks(db, _CHAT_ID, status=TaskStatus.BLOCKED)
        done_task = list_tasks(db, _CHAT_ID, status=TaskStatus.DONE)
        decisions = list_decisions(db, _CHAT_ID, limit=5)
        overdue   = list_overdue_tasks(db, _CHAT_ID)

        goal_str      = sg.goal if sg else None
        prog_strs     = [t.short_str() for t in prog_task]
        blocked_strs  = [(t.short_str(), t.blocker or "No details") for t in blocked]
        open_strs     = [t.short_str() for t in open_task[:8]]
        overdue_strs  = [t.short_str() for t in overdue]
        done_count    = len(done_task)
        decision_strs = [d.short_str() for d in decisions]
 
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines = [f"*Status Update — {today}*\n"]
 
    if goal_str:
        lines.append(f"Sprint Goal: {goal_str}\n")
 
    lines.append(f"In Progress ({len(prog_strs)}):")
    lines += [f"  • {s}" for s in prog_strs] or ["  None"]
 
    lines.append(f"\nBlocked ({len(blocked_strs)}):")
    lines += [f"  • {s}\n    ↳ {b}" for s, b in blocked_strs] or ["  None"]
 
    lines.append(f"\nOpen ({len(open_strs)}):")
    lines += [f"  • {s}" for s in open_strs] or ["  None"]
 
    if overdue_strs:
        lines.append(f"\nOverdue ({len(overdue_strs)}):")
        lines += [f"  • {s}" for s in overdue_strs]
 
    lines.append(f"\nDone this sprint: {done_count} tasks")
 
    if decision_strs:
        lines.append(f"\nRecent Decisions:")
        lines += [f"  • {s}" for s in decision_strs]
 
    return "\n".join(lines) 


# Team tools

@tool
def list_team_members_tool() -> str:
    """
    List all known team members in this group.
    Use this to check who is on the team before assigning tasks.
    """
    with get_db() as db:
        members = list_members(db, _CHAT_ID)
        if not members:
            return "No team members added yet."
        lines = [f"Team members ({len(members)}):"]
        for m in members:
            name = f" ({m.full_name})" if m.full_name else ""
            lines.append(f"  • {m.display()}{name}")
    return "\n".join(lines)
    


# All tools

ALL_TOOLS = [
    create_task_tool,
    list_tasks_tool,
    update_task_tool,
    update_task_status_tool,
    log_decision_tool,
    list_decisions_tool,
    set_sprint_goal_tool,
    get_sprint_goal_tool,
    generate_summary_tool,
    list_team_members_tool
]