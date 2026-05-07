"""Унифицированный vision-клиент: один интерфейс для OpenAI / Anthropic / Google
через ProxyAPI. Маршрутизация по префиксу model name."""

from __future__ import annotations
import base64
import json
import re
from pathlib import Path
from openai import AsyncOpenAI
from anthropic import AsyncAnthropic
from google import genai
from google.genai import types as gtypes

from shared.config import PROXY_API_KEY

OPENAI_BASE    = "https://api.proxyapi.ru/openai/v1"
ANTHROPIC_BASE = "https://api.proxyapi.ru/anthropic"
GOOGLE_BASE    = "https://api.proxyapi.ru/google"

# Тарифы ProxyAPI (USD за 1M токенов) — фактическая цена с наценкой и НДС.
# Источник: https://proxyapi.ru/pricing (наценка ~×3.2 над базовыми ставками провайдера).
# Сконвертировано из RUB по курсу ≈80 руб/USD.
PRICING = {
    "gpt-4.1-mini":      (1.30,   5.16),
    "gpt-4o":            (8.06,  32.21),
    "gpt-4.1":           (6.45,  25.78),
    "gpt-4o-mini":       (0.49,   1.94),
    "claude-sonnet-4-5": (9.68,  48.33),
    "claude-sonnet-4-6": (9.68,  48.33),
    "claude-haiku-4-5":  (3.69,  18.43),
    "gemini-2.5-pro":    (4.04,  32.21),
    "gemini-2.5-flash":  (0.98,   8.06),
}

SYSTEM_PROMPT = """Ты — эксперт-нутрициолог и фуд-аналитик.
По фотографии определи состав блюда, примерный вес каждого ингредиента и общую КБЖУ.

Отвечай СТРОГО в JSON-формате, без лишнего текста, без markdown-обёрток:
{
  "dish_ru": "...",
  "dish_en": "...",
  "portion_grams": 0,
  "ingredients": [
    {"name_ru": "...", "name_en": "...", "grams": 0, "confidence": 0.0}
  ],
  "kcal": 0,
  "protein_g": 0,
  "fat_g": 0,
  "carbs_g": 0,
  "notes": "..."
}

Требования:
- name_en должен быть максимально конкретным (например "boiled white rice", "chicken breast grilled")
- сумма grams ингредиентов должна примерно равняться portion_grams
- kcal/protein_g/fat_g/carbs_g — оценка на всю порцию
"""


def _b64(image_path: Path) -> str:
    return base64.standard_b64encode(open(image_path, "rb").read()).decode()


def _extract_json(text: str) -> dict:
    """Пытаемся распарсить JSON. Если есть markdown-обёртка — снимаем её."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```\s*$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            return json.loads(m.group(0))
        raise


# --- OpenAI ---
_openai_client = None
def _oai() -> AsyncOpenAI:
    global _openai_client
    if _openai_client is None:
        _openai_client = AsyncOpenAI(api_key=PROXY_API_KEY, base_url=OPENAI_BASE)
    return _openai_client


def _user_text(hint: str | None) -> str:
    base = "Проанализируй блюдо на фото."
    if hint:
        base += (
            f"\n\nДополнительная информация: блюдо содержит следующие ингредиенты — {hint}. "
            "Это надёжный список компонентов; используй его при анализе и оцени массы и КБЖУ "
            "с учётом того, что именно эти продукты на тарелке."
        )
    return base


def _ensure_paths(image_paths) -> list[Path]:
    if isinstance(image_paths, (str, Path)):
        return [Path(image_paths)]
    return [Path(p) for p in image_paths]


def _multiview_text(hint: str | None, n_views: int) -> str:
    base = _user_text(hint)
    if n_views > 1:
        prefix = (f"Ниже приведены {n_views} фотографии ОДНОГО И ТОГО ЖЕ блюда с разных ракурсов "
                  f"(сверху и сбоку). Используй все ракурсы для более точной оценки объёма "
                  f"и масс ингредиентов. ")
        return prefix + base
    return base


async def _call_openai(image_paths, model: str, hint: str | None = None) -> tuple[dict, int, int]:
    paths = _ensure_paths(image_paths)
    content: list = [{"type": "text", "text": _multiview_text(hint, len(paths))}]
    for p in paths:
        b64 = _b64(p)
        content.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}})
    response = await _oai().chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": content},
        ],
        temperature=0,
        max_tokens=800,
        response_format={"type": "json_object"},
    )
    parsed = _extract_json(response.choices[0].message.content)
    return parsed, response.usage.prompt_tokens, response.usage.completion_tokens


# --- Anthropic Claude ---
_anthropic_client = None
def _anth() -> AsyncAnthropic:
    global _anthropic_client
    if _anthropic_client is None:
        _anthropic_client = AsyncAnthropic(api_key=PROXY_API_KEY, base_url=ANTHROPIC_BASE)
    return _anthropic_client


async def _call_anthropic(image_paths, model: str, hint: str | None = None) -> tuple[dict, int, int]:
    paths = _ensure_paths(image_paths)
    content: list = []
    for p in paths:
        b64 = _b64(p)
        content.append({"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b64}})
    content.append({"type": "text", "text": _multiview_text(hint, len(paths)) + " Отвечай только JSON."})
    response = await _anth().messages.create(
        model=model,
        max_tokens=800,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": content}],
    )
    text = "".join(b.text for b in response.content if hasattr(b, "text"))
    parsed = _extract_json(text)
    return parsed, response.usage.input_tokens, response.usage.output_tokens


# --- Google Gemini ---
_google_client = None
def _gem():
    global _google_client
    if _google_client is None:
        _google_client = genai.Client(
            api_key=PROXY_API_KEY,
            http_options=gtypes.HttpOptions(base_url=GOOGLE_BASE),
        )
    return _google_client


async def _call_gemini(image_paths, model: str, hint: str | None = None) -> tuple[dict, int, int]:
    paths = _ensure_paths(image_paths)

    # Gemini 2.5 Pro обязательно «думает» — thinking-токены съедают бюджет.
    # Pro: thinking_budget min = 128 (нельзя 0), задаём минимум.
    # Flash: thinking_budget=0 отключает thinking совсем.
    thinking_kwargs = {}
    if "pro" in model:
        thinking_kwargs["thinking_config"] = gtypes.ThinkingConfig(thinking_budget=128)
        max_out = 2048  # запас на минимальный thinking + JSON
    elif "flash" in model:
        thinking_kwargs["thinking_config"] = gtypes.ThinkingConfig(thinking_budget=0)
        max_out = 1024
    else:
        max_out = 1024

    config = gtypes.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        response_mime_type="application/json",
        temperature=0,
        max_output_tokens=max_out,
        **thinking_kwargs,
    )
    contents: list = []
    for p in paths:
        contents.append(gtypes.Part.from_bytes(data=open(p, "rb").read(), mime_type="image/png"))
    contents.append(_multiview_text(hint, len(paths)))
    response = await _gem().aio.models.generate_content(
        model=model,
        contents=contents,
        config=config,
    )
    if not response.text:
        raise ValueError(f"empty text, finish_reason={response.candidates[0].finish_reason}")
    parsed = _extract_json(response.text)
    p_tok = response.usage_metadata.prompt_token_count or 0
    c_tok = (response.usage_metadata.candidates_token_count or 0) + \
            (getattr(response.usage_metadata, "thoughts_token_count", 0) or 0)
    return parsed, p_tok, c_tok


IDENTIFY_PROMPT = """Ты — фуд-аналитик. Перечисли ингредиенты, видимые на фото, на английском языке.
Только список через запятую, максимально конкретные названия (например "boiled white rice", "chicken breast grilled", "olive oil").
Не указывай массы. Не пиши ничего кроме списка."""


async def identify_ingredients(image_paths, model: str) -> tuple[str, int, int]:
    """Шаг 1 двухпроходной схемы: получить от модели список ингредиентов.
    image_paths — Path или список Path (multi-view).
    Возвращает (строка через запятую, prompt_tokens, completion_tokens)."""
    paths = _ensure_paths(image_paths)
    user_text = "Перечисли ингредиенты на фото."
    if len(paths) > 1:
        user_text = f"Ниже {len(paths)} ракурса одного и того же блюда. " + user_text

    if model.startswith("gpt-") or model.startswith("o1-"):
        content: list = [{"type": "text", "text": user_text}]
        for p in paths:
            b64 = _b64(p)
            content.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}})
        response = await _oai().chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": IDENTIFY_PROMPT},
                {"role": "user", "content": content},
            ],
            temperature=0,
            max_tokens=200,
        )
        text = response.choices[0].message.content.strip()
        return text, response.usage.prompt_tokens, response.usage.completion_tokens

    if model.startswith("claude-"):
        b64 = _b64(image_path)
        response = await _anth().messages.create(
            model=model, max_tokens=200, system=IDENTIFY_PROMPT,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b64}},
                {"type": "text", "text": "Перечисли ингредиенты на фото."},
            ]}],
        )
        text = "".join(b.text for b in response.content if hasattr(b, "text")).strip()
        return text, response.usage.input_tokens, response.usage.output_tokens

    if model.startswith("gemini-"):
        image_bytes = open(image_path, "rb").read()
        kwargs = {}
        if "pro" in model:
            kwargs["thinking_config"] = gtypes.ThinkingConfig(thinking_budget=128)
        elif "flash" in model:
            kwargs["thinking_config"] = gtypes.ThinkingConfig(thinking_budget=0)
        config = gtypes.GenerateContentConfig(
            system_instruction=IDENTIFY_PROMPT, temperature=0, max_output_tokens=512, **kwargs,
        )
        response = await _gem().aio.models.generate_content(
            model=model,
            contents=[gtypes.Part.from_bytes(data=image_bytes, mime_type="image/png"),
                      "Перечисли ингредиенты на фото."],
            config=config,
        )
        text = (response.text or "").strip()
        p_tok = response.usage_metadata.prompt_token_count or 0
        c_tok = (response.usage_metadata.candidates_token_count or 0) + \
                (getattr(response.usage_metadata, "thoughts_token_count", 0) or 0)
        return text, p_tok, c_tok

    raise ValueError(f"Неизвестный провайдер для модели: {model}")


# --- Маршрутизатор ---
async def analyze_dish(image_paths, model: str, hint: str | None = None) -> tuple[dict, int, int]:
    """Возвращает (parsed_json, prompt_tokens, completion_tokens).

    image_paths — Path или список Path (для multi-view). Если несколько,
    user-сообщение содержит явное указание что это разные ракурсы одного блюда.

    Если задан hint — строка с подсказкой о составе блюда (имена ингредиентов).
    """
    if model.startswith("gpt-") or model.startswith("o1-"):
        return await _call_openai(image_paths, model, hint)
    if model.startswith("claude-"):
        return await _call_anthropic(image_paths, model, hint)
    if model.startswith("gemini-"):
        return await _call_gemini(image_paths, model, hint)
    raise ValueError(f"Неизвестный провайдер для модели: {model}")


def cost_for_tokens(model: str, p_tok: int, c_tok: int) -> float:
    """USD по фактическим тарифам ProxyAPI (наценка уже включена в PRICING)."""
    inp, outp = PRICING.get(model, (1.30, 5.16))
    return (p_tok * inp + c_tok * outp) / 1e6
