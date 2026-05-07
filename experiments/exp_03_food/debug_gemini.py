"""Отладка Gemini: смотрим что она реально возвращает на одном блюде."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from google import genai
from google.genai import types as gtypes
from shared.config import PROXY_API_KEY
from shared.vision_multi import SYSTEM_PROMPT, GOOGLE_BASE

DATASET_DIR = Path(__file__).parent / "dataset"


async def main():
    # Берём первое блюдо
    import json
    gt_path = DATASET_DIR / "ground_truth.jsonl"
    first = json.loads(open(gt_path).readline())
    image_path = DATASET_DIR / "images" / f"{first['dish_id']}.png"
    image_bytes = open(image_path, "rb").read()

    client = genai.Client(
        api_key=PROXY_API_KEY,
        http_options=gtypes.HttpOptions(base_url=GOOGLE_BASE),
    )

    print(f"=== gemini-2.5-pro, dish {first['dish_id']} ===")
    config = gtypes.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        response_mime_type="application/json",
        temperature=0,
        max_output_tokens=800,
    )
    try:
        resp = await client.aio.models.generate_content(
            model="gemini-2.5-pro",
            contents=[
                gtypes.Part.from_bytes(data=image_bytes, mime_type="image/png"),
                "Проанализируй блюдо на фото.",
            ],
            config=config,
        )
        print(f"finish_reason: {resp.candidates[0].finish_reason}")
        print(f"prompt_tokens: {resp.usage_metadata.prompt_token_count}")
        print(f"thoughts_tokens: {getattr(resp.usage_metadata, 'thoughts_token_count', 0)}")
        print(f"candidates_tokens: {resp.usage_metadata.candidates_token_count}")
        print(f"total_tokens: {resp.usage_metadata.total_token_count}")
        print(f"\nRAW response.text:\n{resp.text!r}")
    except Exception as e:
        print(f"EXCEPTION: {type(e).__name__}: {e}")


asyncio.run(main())
