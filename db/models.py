"""
db/models.py — SQLAlchemy ORM models.

Tables:
  - tasks          core task entity
  - decisions      logged product/team decisions
  - sprint_goals   one active goal per chat
  - chat_messages  rolling conversation history per chat
  - team_members   known Telegram users in the group
"""

from datetime import datetime
from sqlalchemy import (Column, Integer, String, Text, Boolean, DateTime, ForeignKey, Enum as SAEnum)
from sqlalchemy.orm import DeclarativeBase, relationship
import enum


class Base(DeclarativeBase):
    pass


# Enums

class TaskStatus(str, enum.Enum):
    OPEN        = "Open"
    IN_PROGRESS = "In Progress"
    BLOCKED     = "Blocked"
    DONE        = "Done"
    CANCELLED   = "Cancelled"


class TaskPriority(str, enum.Enum):
    CRITICAL = "Critical"
    HIGH     = "High"
    MEDIUM   = "Medium"
    LOW      = "Low"


# Models

class Task(Base):
    __tablename__ = "tasks"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    chat_id     = Column(String, nullable=False, index=True)

    title       = Column(String(300), nullable=False)
    description = Column(Text, nullable=True)

    assignee_username = Column(String(100), nullable=True)   # telegram @username
    assignee_name     = Column(String(100), nullable=True)   # display name

    priority    = Column(SAEnum(TaskPriority), default=TaskPriority.MEDIUM, nullable=False)
    status      = Column(SAEnum(TaskStatus),   default=TaskStatus.OPEN,     nullable=False)

    due_date    = Column(String(50), nullable=True)
    created_at  = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at  = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    closed_at   = Column(DateTime, nullable=True)

    def __repr__(self):
        return f"<Task #{self.id} [{self.status}] {self.title!r}>"

    def short_str(self) -> str:
        due = f" · due {self.due_date}" if self.due_date else ""
        assignee = f" → {self.assignee_username or self.assignee_name or 'Unassigned'}"
        return f"#{self.id} [{self.status}] {self.priority} — {self.title}{assignee}{due}"


class Decision(Base):
    __tablename__ = "decisions"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    chat_id    = Column(String, nullable=False, index=True)

    summary    = Column(String(500), nullable=False)
    owner      = Column(String(100), nullable=True)          # person/role who owns this

    logged_at  = Column(DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f"<Decision #{self.id} {self.summary!r}>"

    def short_str(self) -> str:
        owner = f" ({self.owner})" if self.owner else ""
        return f"#{self.id}{owner} — {self.summary}"


class SprintGoal(Base):
    __tablename__ = "sprint_goals"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    chat_id    = Column(String, nullable=False, unique=True, index=True)

    goal       = Column(Text, nullable=False)
    set_at     = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<SprintGoal {self.goal!r}>"


class ChatMessage(Base):
    """Rolling conversation history — agent reads last N rows per chat."""
    __tablename__ = "chat_messages"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    chat_id    = Column(String, nullable=False, index=True)

    role       = Column(String(20), nullable=False)          # "user" | "assistant"
    content    = Column(Text, nullable=False)
    sender     = Column(String(100), nullable=True)          # display name of human sender

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f"<ChatMessage {self.role} {self.content[:40]!r}>"


class TeamMember(Base):
    """
    Tracks known Telegram users so the scheduler can DM them.
    Populated whenever someone sends a message the bot can see.
    """
    __tablename__ = "team_members"

    id               = Column(Integer, primary_key=True, autoincrement=True)
    chat_id          = Column(String, nullable=False, index=True)

    telegram_user_id = Column(String, nullable=False)        # Telegram numeric user ID
    username         = Column(String(100), nullable=True)    # @username (may be None)
    full_name        = Column(String(200), nullable=True)

    last_seen        = Column(DateTime, default=datetime.utcnow)
    is_active        = Column(Boolean, default=True)

    def __repr__(self):
        return f"<TeamMember @{self.username or self.telegram_user_id}>"

    def display(self) -> str:
        if self.username:
            return f"@{self.username}"
        return self.full_name or str(self.telegram_user_id)