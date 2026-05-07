"""V1 — чистая оценка LLM без обращения к справочнику."""

from __future__ import annotations

CONFIG_NAME = "V1"


def estimate(vision_output: dict) -> dict | None:
    """Берём kcal/p/f/c напрямую из ответа модели."""
    try:
        return {
            "kcal":    float(vision_output.get("kcal", 0)),
            "protein": float(vision_output.get("protein_g", 0)),
            "fat":     float(vision_output.get("fat_g", 0)),
            "carbs":   float(vision_output.get("carbs_g", 0)),
            "source":  "llm_direct",
        }
    except (ValueError, TypeError):
        return None
