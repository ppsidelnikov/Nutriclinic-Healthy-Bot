"""
Прогон V1-V4 на подвыборке Nutrition5k.

Для каждого блюда:
  1. Один вызов vision-LLM → структурированный JSON
  2. V1 — kcal/p/f/c напрямую из модели
  3. V2 — поиск в FatSecret по названию блюда
  4. V3 — поиск по каждому ингредиенту, сумма
  5. V4 — ансамбль V2+V3

Использование:
  python run.py --pilot                      # на ground_truth_pilot.jsonl
  python run.py                              # полный датасет (300)
  python run.py --suffix pilot --limit 5     # отладка
"""

from __future__ import annotations
import asyncio
import json
import sys
import time
import argparse
from pathlib import Path
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).parent.parent))
from shared.vision_multi import analyze_dish, identify_ingredients, cost_for_tokens
from configs import (
    v1_pure_llm, v2_search_by_dish, v3_search_by_ingredients,
    v4_ensemble, v5_recipe_decomposition,
)

DATASET_DIR = Path(__file__).parent / "dataset"
RESULTS_DIR = Path(__file__).parent / "results"

ALL_CONFIGS = [v1_pure_llm, v2_search_by_dish, v3_search_by_ingredients, v4_ensemble, v5_recipe_decomposition]
V1_ONLY = [v1_pure_llm]


def load_ground_truth(suffix: str) -> list[dict]:
    name = f"ground_truth{('_' + suffix) if suffix else ''}.jsonl"
    path = DATASET_DIR / name
    if not path.exists():
        sys.exit(f"Ground truth не найден: {path}\nЗапусти prepare_dataset.py")
    return [json.loads(line) for line in open(path) if line.strip()]


async def process_dish(dish: dict, image_dir: Path, model: str, configs: list,
                       use_hint: bool = False, two_pass: bool = False,
                       identifier_model: str | None = None,
                       multi_view: bool = False) -> dict:
    image_path = image_dir / f"{dish['dish_id']}.png"
    if not image_path.exists():
        return {"dish_id": dish["dish_id"], "error": "no_image"}

    # Список фото: основной (overhead) + опционально боковые ракурсы.
    # В Nutrition5k не у каждого блюда есть все 4 камеры, поэтому берём те что нашлись.
    image_paths = [image_path]
    if multi_view:
        mv_dir = image_dir.parent / "images_multiview"
        for cam in ["A", "B", "C", "D"]:
            mv = mv_dir / f"{dish['dish_id']}_cam{cam}.png"
            if mv.exists():
                image_paths.append(mv)
                if len(image_paths) >= 3:  # overhead + 2 боковых = max 3 фото
                    break

    hint = None
    identify_p_tok = identify_c_tok = 0
    identified_text = None

    if two_pass:
        try:
            id_model = identifier_model or model
            identified_text, identify_p_tok, identify_c_tok = await identify_ingredients(image_paths, model=id_model)
            hint = identified_text
        except Exception as e:
            return {"dish_id": dish["dish_id"], "error": f"identify_fail: {e}"}
    elif use_hint:
        names = [i.get("name", "") for i in dish.get("ingredients", []) if i.get("name")]
        hint = ", ".join(names) if names else None

    t0 = time.perf_counter()
    try:
        vision_out, p_tok, c_tok = await analyze_dish(image_paths, model=model, hint=hint)
    except Exception as e:
        return {"dish_id": dish["dish_id"], "error": f"vision_fail: {e}"}
    vision_ms = (time.perf_counter() - t0) * 1000

    estimates = {}
    for cfg in configs:
        t1 = time.perf_counter()
        try:
            est = cfg.estimate(vision_out)
            if asyncio.iscoroutine(est):
                est = await est
        except Exception as e:
            est = {"error": str(e)}
        estimates[cfg.CONFIG_NAME] = {
            **(est or {}),
            "latency_ms": round((time.perf_counter() - t1) * 1000, 1),
        }

    return {
        "dish_id":           dish["dish_id"],
        "ground_truth":      {"kcal": dish["kcal"], "protein": dish["protein_g"], "fat": dish["fat_g"], "carbs": dish["carbs_g"]},
        "weight_g":          dish["weight_g"],
        "n_ingredients":     len(dish["ingredients"]),
        "vision_output":     vision_out,
        "vision_latency_ms": round(vision_ms, 1),
        "vision_tokens":     {"prompt": p_tok, "completion": c_tok},
        "identified":        identified_text,
        "identify_tokens":   {"prompt": identify_p_tok, "completion": identify_c_tok} if two_pass else None,
        "estimates":         estimates,
    }


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--suffix", default="", help="Суффикс ground_truth-файла (например 'pilot')")
    parser.add_argument("--pilot",  action="store_true", help="Сокращение для --suffix pilot")
    parser.add_argument("--limit",  type=int, help="Ограничить число блюд")
    parser.add_argument("--model",  default="gpt-4.1-mini", help="Vision-модель")
    parser.add_argument("--recipe-model", default="gpt-4.1-mini",
                        help="Модель для V5 recipe-вызова (по умолчанию gpt-4.1-mini)")
    parser.add_argument("--tag", default="",
                        help="Суффикс выходного файла, например 'gpt4o'. Не путать с --suffix (тот для GT).")
    parser.add_argument("--v1-only", action="store_true",
                        help="Прогон только V1 (для cross-model сравнения)")
    parser.add_argument("--resume", action="store_true",
                        help="Дописать к существующему runs_<tag>.jsonl, пропустив уже обработанные dish_id")
    parser.add_argument("--hint", action="store_true",
                        help="Подмешать в промпт список ингредиентов из ground truth (эксперимент «идеальная идентификация»)")
    parser.add_argument("--two-pass", action="store_true",
                        help="Двухпроходный V6: шаг 1 — модель сама распознаёт ингредиенты; шаг 2 — V1 с этим списком как hint")
    parser.add_argument("--identifier-model", default=None,
                        help="Модель для шага 1 двухпроходной схемы (по умолчанию = --model)")
    parser.add_argument("--multi-view", action="store_true",
                        help="V7: подавать в модель overhead + 2 боковых ракурса (cam_A и cam_C из Nutrition5k)")
    args = parser.parse_args()

    suffix = "pilot" if args.pilot else args.suffix
    out_tag = args.tag or suffix
    dishes = load_ground_truth(suffix)
    if args.limit:
        dishes = dishes[: args.limit]

    configs = V1_ONLY if args.v1_only else ALL_CONFIGS
    if not args.v1_only:
        from configs.v5_recipe_decomposition import set_recipe_model
        set_recipe_model(args.recipe_model)

    cfg_names = ", ".join(c.CONFIG_NAME for c in configs)
    print(f"Прогон [{cfg_names}] на {len(dishes)} блюдах")
    print(f"  vision-модель:       {args.model}")
    if not args.v1_only:
        print(f"  recipe-модель (V5):  {args.recipe_model}")
    if args.hint:
        print(f"  hint (ground truth ингредиенты): ВКЛ")
    if args.two_pass:
        id_model = args.identifier_model or args.model
        print(f"  two-pass V6: identifier={id_model}, estimator={args.model}")
    if args.multi_view:
        print(f"  multi-view V7: overhead + cam_A + cam_C")
    print(f"  выходной тег:        '{out_tag}'\n")

    image_dir = DATASET_DIR / "images"
    RESULTS_DIR.mkdir(exist_ok=True)
    out_path = RESULTS_DIR / f"runs{('_' + out_tag) if out_tag else ''}.jsonl"

    # Resume: прочитать уже обработанные dish_id из существующего файла
    done_ids = set()
    if args.resume and out_path.exists():
        for line in open(out_path):
            line = line.strip()
            if not line:
                continue
            try:
                done_ids.add(json.loads(line)["dish_id"])
            except (json.JSONDecodeError, KeyError):
                pass
        print(f"Resume: пропускаю {len(done_ids)} уже обработанных блюд из {out_path.name}\n")

    todo = [d for d in dishes if d["dish_id"] not in done_ids]
    if not todo:
        print("Все блюда уже обработаны, нечего догонять.")
        return

    file_mode = "a" if args.resume else "w"
    pbar = tqdm(todo, desc="dishes", unit="d", ncols=90, colour="cyan")
    total_p_tok, total_c_tok = 0, 0
    with open(out_path, file_mode) as f:
        for d in pbar:
            r = await process_dish(d, image_dir, args.model, configs,
                                   use_hint=args.hint, two_pass=args.two_pass,
                                   identifier_model=args.identifier_model,
                                   multi_view=args.multi_view)
            # Инкрементальный flush — даже при разрыве сети уже обработанные сохранены
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            f.flush()
            if "vision_tokens" in r:
                total_p_tok += r["vision_tokens"]["prompt"]
                total_c_tok += r["vision_tokens"]["completion"]
            first_cfg = configs[0].CONFIG_NAME
            ok = r.get("estimates", {}).get(first_cfg, {}).get("kcal")
            pbar.set_postfix_str(f"{first_cfg}_kcal={ok:.0f}" if ok else "fail")

    print(f"\nСохранено: {out_path}")
    print(f"Vision-токены за этот прогон: prompt={total_p_tok:,}  completion={total_c_tok:,}")
    cost = cost_for_tokens(args.model, total_p_tok, total_c_tok)
    print(f"Vision стоимость ({args.model}): ${cost:.3f} (~{cost*92:.1f} руб)")


if __name__ == "__main__":
    asyncio.run(main())
