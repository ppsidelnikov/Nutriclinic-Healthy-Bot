import re
from typing import Dict, Optional

# Regex helpers reused by both cached API and cache service
SERVING_NUTR_RX = re.compile(
    r"""(?ix)
    \bPer\s*(?P<serving_text>[^-]+?)\s*-\s*            # Per ... -
    Calories:\s*(?P<kcal>[\d\.,]+)\s*kcal              # Calories: 1753kcal
    (?:\s*\|\s*Fat:\s*(?P<fat>[\d\.,]+)\s*g)?          # optional Fat: 43.48g
    (?:\s*\|\s*Carbs?:\s*(?P<carbs>[\d\.,]+)\s*g)?     # optional Carbs: 231.19g
    (?:\s*\|\s*Protein:\s*(?P<protein>[\d\.,]+)\s*g)?  # optional Protein: 115.74g
    """,
)

G_IN_TEXT_RX = re.compile(r"(?i)\b([\d\.,]+)\s*g\b")
G_IN_PARENS_RX = re.compile(r"(?i)\(\s*([\d\.,]+)\s*g\s*\)")
ML_RX = re.compile(r"(?i)\b([\d\.,]+)\s*ml\b")
OZ_RX = re.compile(r"(?i)\b([\d\.,]+)\s*oz\b")


def _to_float(x: Optional[str]) -> Optional[float]:
    if x is None:
        return None
    try:
        return float(x.replace(",", "").strip())
    except Exception:
        return None


def _serving_grams(serving_text: str) -> Optional[float]:
    s = serving_text or ""

    m = G_IN_TEXT_RX.search(s)
    if m:
        return _to_float(m.group(1))

    m = G_IN_PARENS_RX.search(s)
    if m:
        return _to_float(m.group(1))

    m = ML_RX.search(s)
    if m:
        ml = _to_float(m.group(1))
        return ml

    m = OZ_RX.search(s)
    if m:
        oz = _to_float(m.group(1))
        if oz is not None:
            return oz * 28.349523125

    if re.search(r"(?i)\b100\s*g\b", s):
        return 100.0

    return None


def parse_food_description(desc: str) -> Dict[str, Optional[float]]:
    """
    Parse FatSecret food_description and return per-100g nutrition values.
    """
    m = SERVING_NUTR_RX.search(desc or "")
    if not m:
        return {
            "kcal_100g": None,
            "protein_100g": None,
            "fat_100g": None,
            "carbs_100g": None,
            "serving_g": None,
            "source_per": None,
        }

    serving_text = (m.group("serving_text") or "").strip()
    serving_g = _serving_grams(serving_text)

    kcal = _to_float(m.group("kcal"))
    fat = _to_float(m.group("fat"))
    carbs = _to_float(m.group("carbs"))
    protein = _to_float(m.group("protein"))

    if serving_g is None or serving_g <= 0:
        return {
            "kcal_100g": None if kcal is None else None,
            "protein_100g": None,
            "fat_100g": None,
            "carbs_100g": None,
            "serving_g": None,
            "source_per": serving_text,
        }

    if abs(serving_g - 100.0) < 1e-6:
        return {
            "kcal_100g": kcal,
            "protein_100g": protein,
            "fat_100g": fat,
            "carbs_100g": carbs,
            "serving_g": serving_g,
            "source_per": serving_text,
        }

    factor = 100.0 / serving_g
    return {
        "kcal_100g": (kcal * factor) if kcal is not None else None,
        "protein_100g": (protein * factor) if protein is not None else None,
        "fat_100g": (fat * factor) if fat is not None else None,
        "carbs_100g": (carbs * factor) if carbs is not None else None,
        "serving_g": serving_g,
        "source_per": serving_text,
    }


