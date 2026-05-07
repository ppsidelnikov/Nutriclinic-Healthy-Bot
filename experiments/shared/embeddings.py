from openai import AsyncOpenAI
from shared.config import PROXY_API_KEY, PROXY_API_BASE_URL, EMBEDDING_MODEL


def _client() -> AsyncOpenAI:
    return AsyncOpenAI(api_key=PROXY_API_KEY, base_url=PROXY_API_BASE_URL)


async def get_embedding(text: str) -> list[float]:
    client = _client()
    response = await client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=text.replace("\n", " "),
    )
    return response.data[0].embedding
