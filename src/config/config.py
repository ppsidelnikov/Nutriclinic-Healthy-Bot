from dotenv import load_dotenv
import os

env_file = os.getenv("ENV_PATH", ".env")
load_dotenv(env_file)

class Config:
    #Telegram
    TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    ADMIN_TELEGRAM_ID = os.getenv('ADMIN_TELEGRAM_ID')
    ADMIN_TELEGRAM_NAME = os.getenv('ADMIN_TELEGRAM_NAME')
    
    # Google Sheets
    GOOGLE_SHEETS_ID = os.getenv("GOOGLE_SHEETS_ID")
    GOOGLE_SHEETS_NAME = os.getenv("GOOGLE_SHEETS_NAME")
    RAW_GSHEETS_LIST = os.getenv("RAW_GSHEETS_LIST")

    #YandexGPT
    YANDEX_GPT_TOKEN = os.getenv('YANDEX_GPT_TOKEN')
    YANDEX_CLOUD_FOLDER_ID = os.getenv('YANDEX_CLOUD_FOLDER_ID')
    YANDEX_GPT_PATH = os.getenv('YANDEX_GPT_PATH')

    #Postgres
    DB_HOST=os.getenv('DB_HOST')
    DB_PORT=os.getenv('DB_PORT')
    DB_NAME=os.getenv('DB_NAME')
    DB_USER=os.getenv('DB_USER')
    DB_PASSWORD=os.getenv('DB_PASSWORD')



# Экспортируем конфиг
config = Config()