"""
The bot is initialised once on startup and reused by both the webhook handler(for incoming messages) and the scheduler(outgoing pings).
"""

from telegram.ext import Application
from config import get_settings

settings = get_settings()

_app: Application | None = None

def get_bot() -> Application:
    global _app
    if _app is None:
        _app = (Application.builder().token(settings.telegram_bot_token).build())
    return _app


async def send_message(chat_id: str, text: str, parse_mode: str = "Markdown") -> None:
    """Send a message to any user"""
    app = get_bot()
    await app.bot.send_message(chat_id=chat_id, text=text, parse_mode=parse_mode)


async def send_group_message(text: str, parse_mode: str = "Markdown") -> None:
    """send to the configured group."""
    await send_message(settings.telegram_group_id, text, parse_mode)