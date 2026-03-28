import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

REQUIRED_WS_ENV = ['TWELVE_API_KEY', 'TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID']
REQUIRED_NEWS_ENV = ['GROQ_API_KEY', 'TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID']
DATA_DIR = Path('data')


def ensure_data_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def validate_env(required_keys):
    missing = [key for key in required_keys if not os.getenv(key)]
    if missing:
        raise RuntimeError(f'Missing environment variables: {", ".join(missing)}')


def validate_ws_startup():
    ensure_data_dir()
    validate_env(REQUIRED_WS_ENV)


def validate_news_startup():
    ensure_data_dir()
    validate_env(REQUIRED_NEWS_ENV)
