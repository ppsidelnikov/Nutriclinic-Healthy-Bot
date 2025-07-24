from dotenv import load_dotenv
import os

env_file = os.getenv("ENV_PATH", ".env")
load_dotenv(env_file)

class Config:
    # Telegram
    TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    


# Экспортируем конфиг
config = Config()