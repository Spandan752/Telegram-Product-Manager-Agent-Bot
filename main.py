from fastapi import FastAPI
from config import get_settings

settings = get_settings()

app = FastAPI(
    title="Telegram PM Agent API",
    description="API for the Telegram PM Agent, a project management assistant bot.",
    version="1.0.0",
    docs_url="/docs" if settings.debug else None
)

@app.get("/health")
async def health_check():
    return {"status": "ok"}