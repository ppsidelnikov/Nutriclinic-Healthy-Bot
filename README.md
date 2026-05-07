# Nutriclinic Healthy Bot

Telegram-бот — персональный нутрициологический ассистент. Распознаёт еду по фото, ведёт дневник питания с прогрессом к целям по калориям и БЖУ, отвечает на вопросы по нутрициологии на основе авторитетных источников (ВОЗ, DRI, ISSN).

Разработан в рамках магистерской диссертации в НИУ ВШЭ; архитектурные решения обоснованы тремя экспериментами (см. `experiments/`).

---

## Попробовать

**Бот в Telegram:** [@nutriclinic_healthy_testing_bot](https://t.me/nutriclinic_healthy_testing_bot)

---

## Возможности

- 🥗 **Анализ блюда по фото** — двухпроходный V6-пайплайн (identify → estimate) на `gpt-4.1-mini`. wMAPE по килокалориям ≈ 33 % на стратифицированной выборке Nutrition5k (см. §3.1 диссертации).
- 📔 **Дневник питания** — записи через фото, текст или авто-сохранёнки; разбивка по приёмам пищи, прогресс к цели с цветовыми индикаторами 🔵🟢🟡🟠🔴, streak дней подряд.
- 💬 **RAG-консультант** — гибридный поиск (dense + BM25) с переводом запроса RU→EN и кросс-энкодерным переранжированием по корпусу из 21 источника (~2300 чанков). Faithfulness 0.64 на размеченном QA-наборе (см. §3.2).
- 🛠 **Function calling** — модель сама обращается к историческим данным пользователя через 5 tools (`get_weight_history`, `get_diary_for_date`, `quick_add_food` и др.), описано в §2.4.
- ⚖️ **Учёт веса** — динамика за неделю/месяц, авто-пересчёт целевых калорий по формуле Миффлина-Сан Жеора.
- 🎯 **Цель по калориям** — авто-расчёт из профиля или ручная установка.

Полный список команд — в `/help` бота.

---

## Архитектура

```
                    ┌─────────────────┐
                    │   Telegram API  │
                    └────────┬────────┘
                             │ long polling
              ┌──────────────▼──────────────┐
              │     Bot (aiogram + asyncio) │
              │  ─ handlers/                │
              │  ─ services/                │
              │  ─ tools (function calling) │
              └──────────────┬──────────────┘
                ┌────────────┼────────────┐
                ▼            ▼            ▼
         ┌──────────┐ ┌──────────┐ ┌──────────┐
         │ Postgres │ │  Redis   │ │  MinIO   │
         │ +pgvector│ │ history  │ │  photos  │
         └──────────┘ └──────────┘ └──────────┘
                │
        knowledge_chunks (RAG corpus, IVFFLAT index)
        food_diary, weight_log, user_profile, chat_messages

         ┌─────────────────────────────────────────┐
         │          External APIs (ProxyAPI)       │
         │   gpt-4.1-mini / vision / embeddings    │
         │   cross-encoder mmarco (локально, CPU)  │
         └─────────────────────────────────────────┘
```

### Модули `src/`

| Путь | Назначение |
|------|-----------|
| `main.py` | Точка входа, прогрев RAG, polling |
| `bot_setup.py` | aiogram dispatcher и bot |
| `middlewares.py` | Логирование сообщений |
| `handlers/base_handlers.py` | `/start`, `/help`, `/profile`, `/weight`, `/set_calories` |
| `handlers/food_calories_count_handlers.py` | Фото-анализ, текстовый чат с RAG и tool-calling |
| `handlers/food_diary_handlers.py` | `/add`, `/today`, `/yesterday`, `/week`, `/saved`, `/undo` |
| `services/photo_recognition.py` | V6 двухпроходный pipeline для фото |
| `services/text_chat.py` | Текстовый нутрициолог-консультант |
| `services/rag.py` | R6: translate + hybrid + rerank + gating |
| `services/tools.py` | Function calling — 5 tools для исторических данных и записи |
| `services/food_diary.py` | CRUD дневника, агрегаты, streak, форматирование |
| `services/food_parser.py` | LLM-парсер свободного описания еды |
| `services/weight_log.py` | Учёт веса с авто-обновлением профиля |
| `services/user_profile.py` | CRUD профиля + Миффлин-Сан Жеор |
| `services/chat_history.py` | 2-уровневая память диалога: Redis + Postgres + auto-summary |
| `services/fatsecret_*` | FatSecret-клиент (legacy, V6 не использует) |
| `db/models.py` | SQLAlchemy-модели |
| `db/db.py` | Async engine, sessions |
| `db/db_write.py`, `db/minio_io.py` | Утилиты записи |

---

## Связь с диссертацией

| Раздел | Эксперимент | Принятое решение |
|---|---|---|
| §1.4 | — | ЦА, CJM, конкуренты |
| §2.1 → §3.1 | `experiments/exp_03_food/` | V6 двухпроходный pipeline на `gpt-4.1-mini` |
| §2.2 → §3.2 | `experiments/exp_02_rag/` | R6: translate + hybrid + rerank + gating (θ = −3) |
| §2.3 → §3.3 | `experiments/exp_03_load/` | asyncio.gather + IVFFLAT pgvector; 25 одновременных пользователей на 8 vCPU |
| §2.4 | — (архитектурно) | Function calling для персональных данных |

Каждое архитектурное решение в `src/` имеет ссылку на экспериментальный аналог в `experiments/`.

---

## Эксперименты и воспроизводимость

Полный гайд по запуску экспериментов — `experiments/README.md`.

Ключевые артефакты для проверки результатов диссертации:
- `experiments/exp_02_rag/results/metrics.csv` — RAGAS-метрики для R1–R6
- `experiments/exp_03_food/results/metrics_full_v1v5.csv` — wMAPE/MAPE V1–V7 по 7 моделям
- `experiments/exp_03_load/results/timeline_L1.csv` — посекундная нагрузка для §3.3

---

## Лицензия и контакты

Проект разработан как магистерская работа в НИУ ВШЭ (программа AI),
тема — «Разработка интеллектуальной системы поддержки контроля веса».

Автор: P. Sidelnikov, 2026.

Корпус документов в `docs/` — публичные источники (ВОЗ, NIH, DRI, ISSN, EFSA), используются в исследовательских целях.
