from datetime import datetime, timezone
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import and_

from db.models import Task, TaskStatus, TaskPriority, Decision, SprintGoal, ChatMessage, TeamMember

HISTORY_LIMIT = 20  # no. of recent messages


# TASKS

def create_task(
    db: Session,
    chat_id: str,
    title: str,
    assignee_username: Optional[str] = None,
    assignee_name: Optional[str] = None,
    priority: TaskPriority = TaskPriority.MEDIUM,
    due_date: Optional[str] = None,
    description: Optional[str] = None,
) -> Task:
    """Create a new task and return it (with ID)."""
    task = Task(
        chat_id=chat_id,
        title=title,
        assignee_username=assignee_username,
        assignee_name=assignee_name,
        priority=priority,
        due_date=due_date,
        description=description,
    )
    db.add(task)
    db.flush()   # get the auto-generated ID before commit
    return task


def get_task(db: Session, chat_id: str, task_id: int) -> Optional[Task]:
    return db.query(Task).filter(
        and_(Task.chat_id == chat_id, Task.id == task_id)
    ).first()


def list_tasks(
        db: Session, 
        chat_id: str,  
        status: Optional[TaskStatus] = None, 
        assignee_username: Optional[str] = None
) -> list[Task]:
    q = db.query(Task).filter(Task.chat_id == chat_id)
    if status:
        q = q.filter(Task.status == status)
    if assignee_username:
        q = q.filter(Task.assignee_username == assignee_username.lstrip('@'))
    return q.order_by(Task.id).all()


def list_overdue_tasks(db: Session, chat_id: str) -> list[Task]:
    """Open/in-progress tasks whose due_date is before today."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return db.query(Task).filter(
        and_(
            Task.chat_id == chat_id,
            Task.status.in_([TaskStatus.OPEN, TaskStatus.IN_PROGRESS]),
            Task.due_date != None,
            Task.due_date < today,
        )
    ).all()
 
 
def update_task_status(
    db: Session, 
    chat_id: str, 
    task_id: int, 
    status: TaskStatus
) -> Optional[Task]:
    task = get_task(db, chat_id, task_id)
    if not task:
        return None
    task.status = status
    if status in (TaskStatus.DONE, TaskStatus.CANCELLED):
        task.closed_at = datetime.now(timezone.utc)
    return task
 
 
def update_task_fields(
    db: Session,
    chat_id: str,
    task_id: int,
    **kwargs,
) -> Optional[Task]:
    task = get_task(db, chat_id, task_id)
    if not task:
        return None
    allowed = {"title", "assignee_username", "assignee_name",
               "priority", "due_date", "description", "blocker"}
    for k, v in kwargs.items():
        if k in allowed and v is not None:
            setattr(task, k, v)
    return task



# DECISIONS

def log_decisions(
  db: Session,
  chat_id: str,
  summary: str,
  owner: Optional[str] = None      
) -> Decision:
    """Log a new decision and return it with ID."""
    decision = Decision(
        chat_id=chat_id,
        summary=summary,
        owner = owner
    )

    db.add(decision)
    db.flush()   # get the auto-generated ID before commit
    return decision


def list_decisions(db: Session, chat_id: str, limit: int=20) -> list[Decision]:
    return db.query(Decision).filter(Decision.chat_id == chat_id).order_by(Decision.id.desc()).limit(limit).all()


# Sprint goals

def set_sprint_goal(db: Session, chat_id: str, goal: str) -> SprintGoal:
    existing = db.query(SprintGoal).filter(SprintGoal.chat_id == chat_id).first()
    if existing:
        existing.goal = goal
        existing.updated_at = datetime.utcnow()
        return existing
    sg = SprintGoal(chat_id=chat_id, goal=goal)
    db.add(sg)
    return sg
 
 
def get_sprint_goal(db: Session, chat_id: str) -> Optional[SprintGoal]:
    return db.query(SprintGoal).filter(SprintGoal.chat_id == chat_id).first()


# Chat messages history

def append_message(
    db: Session,
    chat_id: str,
    role: str,
    content: str,
    sender: Optional[str] = None,
) -> ChatMessage:
    msg = ChatMessage(chat_id=chat_id, role=role, content=content, sender=sender)
    db.add(msg)
    db.flush()
    _trim_history(db, chat_id)
    return msg
 
 
def get_history(db: Session, chat_id: str) -> list[ChatMessage]:
    return (
        db.query(ChatMessage)
        .filter(ChatMessage.chat_id == chat_id)
        .order_by(ChatMessage.created_at)
        .limit(HISTORY_LIMIT)
        .all()
    )
 
 
def _trim_history(db: Session, chat_id: str) -> None:
    """Keep only the most recent HISTORY_LIMIT messages."""
    total = db.query(ChatMessage).filter(ChatMessage.chat_id == chat_id).count()
    if total > HISTORY_LIMIT:
        cutoff = total - HISTORY_LIMIT
        oldest_ids = (
            db.query(ChatMessage.id)
            .filter(ChatMessage.chat_id == chat_id)
            .order_by(ChatMessage.created_at)
            .limit(cutoff)
            .subquery()
        )
        db.query(ChatMessage).filter(ChatMessage.id.in_(oldest_ids)).delete(
            synchronize_session=False
        )
 

# Team members

def upsert_member(
    db: Session,
    chat_id: str,
    telegram_user_id: str,
    username: Optional[str] = None,
    full_name: Optional[str] = None,
) -> TeamMember:
    member = db.query(TeamMember).filter(
        and_(
            TeamMember.chat_id == chat_id,
            TeamMember.telegram_user_id == telegram_user_id,
        )
    ).first()
    if member:
        member.username  = username or member.username
        member.full_name = full_name or member.full_name
        member.last_seen = datetime.utcnow()
    else:
        member = TeamMember(
            chat_id=chat_id,
            telegram_user_id=telegram_user_id,
            username=username,
            full_name=full_name,
        )
        db.add(member)
    db.flush()
    return member
 
 
def list_members(db: Session, chat_id: str) -> list[TeamMember]:
    return (
        db.query(TeamMember)
        .filter(and_(TeamMember.chat_id == chat_id, TeamMember.is_active == True))
        .all()
    )
 
 
def get_member_by_username(
    db: Session, chat_id: str, username: str
) -> Optional[TeamMember]:
    return db.query(TeamMember).filter(
        and_(
            TeamMember.chat_id == chat_id,
            TeamMember.username == username.lstrip("@"),
        )
    ).first()