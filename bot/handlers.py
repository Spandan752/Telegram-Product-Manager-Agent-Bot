"""
All telegram handlers are defined here.

Message handler: Any text that mentions the bot or replies to it triggers the agent.
"""

from telegram import Update
from telegram.ext import ContextTypes
from config import get_settings
from agent.graph import run_agent
from db.database import get_db
from db.crud import create_task, upsert_member

settings = get_settings()

# Helper functions

def _sender_name(update: Update) -> str:
    """Get the sender's name from the update."""
    user = update.effective_user
    if not user:
        return "Someone"
    return user.first_name or user.username or "Someone"


def _chat_id(update: Update) -> str:
    """Get the chat ID from the update."""
    return str(update.effective_chat.id)


def _is_group(update: Update) -> bool:
    return update.effective_chat.type in ("group", "supergroup")


# def _should_respond(update: Update) -> bool:
#     """
#     In group chats only respond when:
#       - the bot is @mentioned
#       - the message is a reply to the bot
#     In private chats always respond.
#     """
#     if not _is_group(update):
#         return True
#     text = update.message.text or ""
#     mentioned = f"@{settings.bot_username}" in text
#     reply_to_bot = (
#         update.message.reply_to_message is not None
#         and update.message.reply_to_message.from_user is not None
#         and update.message.reply_to_message.from_user.username == settings.bot_username
#     )
#     return mentioned or reply_to_bot

def _should_respond(update: Update) -> bool:
    """
    In group chats, always pass every message to the agent.
    The LLM decides whether to act — not a keyword filter.
    """
    return True


def _clean_text(text: str) -> str:
    """Strip the bot mention so it doesn't confuse the LLM."""
    return text.replace(f"@{settings.bot_name}", "").strip()


def _track_member(update: Update) -> None:
    """Silently keep team_members table up to date."""
    user = update.effective_user
    if not user or user.is_bot:
        return
    with get_db() as db:
        upsert_member(
            db,
            chat_id=_chat_id(update),
            telegram_user_id=str(user.id),
            username=user.username,
            full_name=user.full_name,
        )


async def _safe_reply(message, text: str, **kwargs) -> None:
    """
    Try sending with Markdown first.
    If Telegram rejects it (bad entities), fall back to plain text.
    """
    try:
        await message.reply_text(text, parse_mode="Markdown", **kwargs)
    except Exception:
        # Strip any markdown symbols and send as plain text
        plain = text.replace("*", "").replace("_", "").replace("`", "").replace("[", "").replace("]", "")
        await message.reply_text(plain, parse_mode=None, **kwargs)

# Commands

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /start command."""
    _track_member(update)
    await update.message.reply_text(
        "👋 Hey! I'm *Alex*, your AI Product Manager.\n\n"
        "I'll track tasks, log decisions, run standups, and keep the team aligned — "
        "all from inside this Telegram group.\n\n"
        "*Commands:*\n"
        "• `/tasks` — open & in-progress tasks\n"
        "• `/decisions` — decision log\n"
        "• `/standup` — status summary\n"
        "• `/sprint <goal>` — set sprint goal\n"
        "• `/help` — this message\n\n"
        "Or just mention me anytime: _@AlexBot can you track that Priya..._\n\n"
        "Let's ship something...",
        parse_mode="Markdown",
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await cmd_start(update, context)


async def cmd_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _track_member(update)
    chat_id = _chat_id(update)
    await update.message.chat.send_action("typing")
    reply = await run_agent(
        chat_id=chat_id,
        user_message="List all open and in-progress tasks.", sender_name=_sender_name(update)
    )
    await _safe_reply(update.message, reply)


async def cmd_decisions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _track_member(update)
    chat_id = _chat_id(update)
    await update.message.chat.send_action("typing")
    reply = await run_agent(
        chat_id=chat_id,
        user_message="List all logged decisions.",
        sender_name=_sender_name(update)
    )
    await _safe_reply(update.message, reply)


async def cmd_standup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _track_member(update)
    chat_id = _chat_id(update)
    await update.message.chat.send_action("typing")
    reply = await run_agent(
        chat_id=chat_id,
        user_message="Generate the standup summary for the team.",
        sender_name=_sender_name(update),
    )
    await _safe_reply(update.message, reply)


async def cmd_sprint(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _track_member(update)
    goal = (update.message.text or "").replace("/sprint", "").strip()
    if not goal:
        await update.message.reply_text(
            "Please provide the sprint goal:\n`/sprint Ship v2 by June 15`",
            parse_mode="Markdown",
        )
        return
    chat_id = _chat_id(update)
    await update.message.chat.send_action("typing")
    reply = await run_agent(
        chat_id=chat_id,
        user_message=f'Set the sprint goal to: "{goal}"',
        sender_name=_sender_name(update),
    )
    await _safe_reply(update.message, reply)


# Message handler for non-command messages

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Main handler — routes any text message through the agent."""
    if not update.message or not update.message.text:
        return 
    
    _track_member(update)

    if not _should_respond(update):
        return
    
    chat_id = _chat_id(update)
    text = _clean_text(update.message.text)
    if not text:
        return
    
    await update.message.chat.send_action("typing")

    try:
        reply = await run_agent(
            chat_id = chat_id,
            user_message=text,
            sender_name = _sender_name(update)
        )

        # Only reply if the agent actually has something to say
        # LLM returns empty or "." to signal intentional silence
        if reply and reply.strip() and reply.strip() not in (".", "...", "-"):

            # await update.message.reply_text(
            #     reply,
            #     parse_mode="Markdown",
            #     reply_to_message_id=update.message.message_id
            # )  
            await _safe_reply(update.message, reply)

    except Exception as e:
        await update.message.reply_text(
            "Something went wrong on my end. Please try again in a moment."
        )
        raise