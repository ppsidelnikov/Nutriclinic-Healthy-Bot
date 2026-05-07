# Эксперимент 1 (§3.1). Точность распознавания на Nutrition5k

## Цель

Сравнить четыре варианта пайплайна оценки КБЖУ по фотографии:
- **V1** — чистая оценка GPT-4 vision без обращения к справочнику
- **V2** — GPT-4 vision + поиск по названию блюда в FatSecret
- **V3** — GPT-4 vision + поиск по ингредиентам с агрегацией пропорционально оценённым массам
- **V4** — ансамбль V2 и V3

Метрики:
- MAE и MAPE по калориям, белкам, жирам, углеводам
- Доля валидных JSON-ответов модели
- Стоимость одного запроса

Дополнительный подэксперимент (на 30–50 блюдах): сравнение моделей GPT-4V / Claude 3.5 Sonnet / Gemini 1.5 Pro.

## Подготовка датасета

Полный Nutrition5k — около 50 ГБ. Нам нужна подвыборка 200–300 блюд:

1. Скачать только метаданные (CSV ingredients & dish-level nutrients) — несколько мегабайт.
2. Стратифицированно отобрать 200–300 блюд (простые / составные / нестандартные порции).
3. Скачать фото только для отобранных блюд (~2–5 ГБ).

Скрипт подготовки: `data/prepare_subset.py` (будет добавлен).

## Запуск (после подготовки данных)

```bash
cd experiments/exp_01_recognition
python data/prepare_subset.py --n 200 --out data/subset/
python run.py --variant V1 --subset data/subset/ --out results/v1.jsonl
python run.py --variant V2 --subset data/subset/ --out results/v2.jsonl
python run.py --variant V3 --subset data/subset/ --out results/v3.jsonl
python run.py --variant V4 --subset data/subset/ --out results/v4.jsonl
python evaluate.py --results results/ --ground-truth data/subset/ground_truth.csv --out results/metrics.csv
```

## Замечания по стоимости

Один вызов GPT-4 vision стоит порядка 0,01–0,05 $ на изображение. На 200 блюдах × 4 варианта = 800 вызовов = ~10–40 $. На дополнительный кросс-сравнение моделей — ещё ~10 $. Итого ~50 $ — учитываем при планировании бюджета.
