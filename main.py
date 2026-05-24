from fastapi import FastAPI, Request, HTTPException
from config import get_settings
# import logging
from contextlib import asynccontextmanager
from telegram import Update
from telegram.ext import CommandHandler, MessageHandler, filters
from config import get_settings
from db.database import create_tables
from bot.telegram import get_bot
from bot.handlers import (
    cmd_start, cmd_help, cmd_tasks, cmd_decisions,
    cmd_standup, cmd_sprint, handle_message,
)
from scheduler.jobs import start_scheduler, stop_scheduler


settings = get_settings()

WEBHOOK_PATH  = f"/webhook/{settings.telegram_bot_token}"
WEBHOOK_URL   = f"{settings.webhook_base_url}{WEBHOOK_PATH}"

# Managing lifespan of the bot

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Create db tables
    create_tables()

    tg_bot = get_bot()

    # Set up Telegram handlers
    tg_bot.add_handler(CommandHandler("start",     cmd_start))
    tg_bot.add_handler(CommandHandler("help",      cmd_help))
    tg_bot.add_handler(CommandHandler("tasks",     cmd_tasks))
    tg_bot.add_handler(CommandHandler("decisions", cmd_decisions))
    tg_bot.add_handler(CommandHandler("standup",   cmd_standup))
    tg_bot.add_handler(CommandHandler("sprint",    cmd_sprint))
    tg_bot.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )
    
    await tg_bot.initialize()

    await tg_bot.bot.set_webhook(
        url=WEBHOOK_URL,
        allowed_updates=["message", "edited_message"],
        drop_pending_updates=True,
    )

    start_scheduler()

    yield  # The app is now running

    # Shutdown: Clean up
    await tg_bot.bot.delete_webhook()
    await tg_bot.shutdown()
    
    stop_scheduler()

# App

app = FastAPI(
    title="Telegram PM Agent",
    description="API for the Telegram PM Agent, a project management assistant bot.",
    version="1.0.0",
    docs_url="/docs" if settings.debug else None,
    lifespan=lifespan
)

# Routes

@app.post(WEBHOOK_PATH)
async def telegram_webhook(request: Request):
    """
    Telegram calls this with every update (message, command, etc.).
    We parse it and dispatch it through python-telegram-bot's handler stack.
    """
    data = await request.json()
    tg_bot = get_bot()
    update = Update.de_json(data, tg_bot.bot)
    await tg_bot.process_update(update)
    return {"ok": True}


@app.get("/health")
async def health_check():
    return {"status": "ok", "agent": "Alex", "version": "1.0.0"}