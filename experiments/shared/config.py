import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

PROXY_API_KEY      = os.getenv("PROXY_API_TEST_KEY")
PROXY_API_BASE_URL = os.getenv("PROXY_API_BASE_URL", "https://api.proxyapi.ru/openai/v1")

DB_URL = (
    f"postgresql+asyncpg://{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}"
    f"@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_NAME')}"
)

EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIM   = 1536
ANSWER_MODEL    = "gpt-4o-mini"

FATSECRET_CLIENT_ID     = os.getenv("FATSECRET_CLIENT_ID")
FATSECRET_CLIENT_SECRET = os.getenv("FATSECRET_CLIENT_SECRET")
