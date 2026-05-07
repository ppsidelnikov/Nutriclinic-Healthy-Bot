# Experiments

Эксперименты, проведённые в рамках магистерской диссертации. Соответствуют главам §3.1–§3.3 и подразделу §1.5 работы.

## Структура

```
experiments/
├── README.md
├── requirements.txt        — общие зависимости для всех экспериментов
├── shared/                 — общие утилиты (config, vision, fatsecret, db)
│
├── exp_01_recognition/     — обзорный анализ Nutrition5k (notebooks)
├── exp_02_rag/             — §3.2 RAG-конфигурации R1–R6
├── exp_03_food/            — §3.1 Photo recognition V1–V7 + cross-model
└── exp_03_load/            — §3.3 Нагрузочное тестирование L1–L4
```

## Связь с главами диссертации

| Эксперимент | Глава | Что валидирует |
|-------------|-------|----------------|
| `exp_02_rag` | §3.2 | Гипотезу о RAG-архитектуре (translate + hybrid + rerank + gating) |
| `exp_03_food` | §3.1 | Гипотезу о пайплайне распознавания фото (V6 two-pass) |
| `exp_03_load` | §3.3 | Серверные оптимизации и сайзинг |
| `exp_01_recognition` | §1.1 (обзор) | Анализ датасета Nutrition5k |

## Запуск

Эксперименты используют отдельный venv (отличается от прод-бота:
sentence-transformers, pandas, ragas, и т.п.).

```bash
cd experiments
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
# .env берётся из корня репозитория
```

Каждый эксперимент имеет свой README с конкретными командами запуска.

## Что не в репозитории

Большие данные намеренно не коммитятся:
- `exp_03_food/dataset/images*` — RGB-кадры Nutrition5k (~1 ГБ); скачиваются через `prepare_dataset.py`.
- `exp_03_food/dataset/_tmp_videos` — временные h264 для multi-view.
- `venv/` — пересобирается на стороне.

`results/*.jsonl` и `results/*.csv` коммитятся выборочно — основные
метрики сохраняются для воспроизводимости таблиц в диссертации.

## Связь с продакшен-кодом

Часть архитектурных решений перенесена из экспериментов в `src/` основного бота:
- R6 RAG (`exp_02_rag/configs/r6_*`) → `src/services/rag.py`
- V6 photo (`exp_03_food/configs/v6_*`) → `src/services/chat_gpt_api.py`

Эксперименты остаются точкой воспроизводимости результатов главы 3,
в проде используются только продакшен-версии.
