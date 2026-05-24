from pydantic_settings import BaseSettings
from functools import lru_cache
import os

class Settings(BaseSettings):
    telegram_token: str
    telegram_group_id: str
    bot_name: str

    gemini_api_key: str = os.getenv("GOOGLE_API_KEY", "")
    model_name: str = os.getenv("MODEL_NAME", "gemini-2.5-flash")
    temperature: float = float(os.getenv("MODEL_TEMPERATURE", 0.7))

    webhook_url: str
    database_url: str = "sqlite:///./pm_agent.db"
    debug: bool = False

    standup_hour: int = 10          # Morning standup ping
    standup_minute: int = 0
    digest_hour: int = 18           # Evening standup
    digest_minute: int = 0
    followup_hour: int = 16         # Overdue task follow-up
    followup_minute: int = 0

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

@lru_cache()
def get_settings():
    return Settings()
