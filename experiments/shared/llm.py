from openai import AsyncOpenAI
from shared.config import PROXY_API_KEY, PROXY_API_BASE_URL, ANSWER_MODEL

SYSTEM_PROMPT = (
    "Ты — нутрициолог-консультант. Отвечай на вопросы пользователя строго на основе "
    "предоставленных материалов. Если материалы не содержат ответа, скажи об этом. "
    "Отвечай по-русски, лаконично (2–4 предложения), без лишних вступлений."
)


def _client() -> AsyncOpenAI:
    return AsyncOpenAI(api_key=PROXY_API_KEY, base_url=PROXY_API_BASE_URL)


async def generate_answer(question: str, chunks: list[str]) -> tuple[str, int, int]:
    """
    Генерирует ответ на вопрос на основе retrieved чанков.
    Возвращает (answer, prompt_tokens, completion_tokens).
    """
    if chunks:
        context = "\n\n---\n\n".join(chunks)
        user_msg = f"Материалы:\n{context}\n\nВопрос: {question}"
    else:
        user_msg = f"Вопрос: {question}"

    client = _client()
    response = await client.chat.completions.create(
        model=ANSWER_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        temperature=0.1,
        max_tokens=512,
    )
    answer = response.choices[0].message.content.strip()
    p_tok = response.usage.prompt_tokens
    c_tok = response.usage.completion_tokens
    return answer, p_tok, c_tok
