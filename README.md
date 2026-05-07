# Nutriclinic Healthy Bot

Telegram-бот — персональный нутрициологический ассистент. Распознаёт еду по фото, ведёт дневник питания с прогрессом к целям по калориям и БЖУ, отвечает на вопросы по нутрициологии на основе авторитетных источников (ВОЗ, DRI, ISSN).

Разработан в рамках магистерской диссертации в НИУ ВШЭ; архитектурные решения обоснованы тремя экспериментами (см. `experiments/`).

---

## Возможности

- 🥗 **Анализ блюда по фото** — двухпроходный V6-пайплайн (identify → estimate) на `gpt-4.1-mini`. wMAPE по килокалориям ≈ 33 % на стратифицированной выборке Nutrition5k (см. §3.1).
- 📔 **Дневник питания** — записи через фото, текст или авто-сохранёнки; разбивка по приёмам пищи, прогресс к цели с цветовыми индикаторами, streak дней подряд.
- 💬 **RAG-консультант** — гибридный поиск (dense + BM25) с переводом запроса RU→EN и кросс-энкодерным переранжированием по корпусу из 21 источника (~2300 чанков). Faithfulness 0.64 на размеченном QA-наборе (см. §3.2).
- 🛠 **Function calling** — модель сама обращается к историческим данным пользователя через 5 tools (`get_weight_history`, `get_diary_for_date`, `quick_add_food` и др.).
- ⚖️ **Учёт веса** — динамика за неделю/месяц, авто-пересчёт целевых калорий по Миффлину-Сан Жеору.
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
              │      Bot (aiogram + asyncio) │
              │  ─ handlers/                 │
              │  ─ services/                 │
              │  ─ tools (function calling)  │
              └──────────────┬───────────────┘
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
| §1.5 | — | ЦА, CJM, конкуренты |
| §2.1 → §3.1 | `experiments/exp_03_food/` | V6 двухпроходный pipeline на `gpt-4.1-mini` |
| §2.2 → §3.2 | `experiments/exp_02_rag/` | R6: translate + hybrid + rerank + gating (θ = −3) |
| §2.3 → §3.3 | `experiments/exp_03_load/` | asyncio.gather + IVFFLAT pgvector; 25 одновременных пользователей на 8 vCPU |
| §2.4 | — (архитектурно) | Function calling для персональных данных |

Каждое архитектурное решение в `src/` имеет ссылку на экспериментальный аналог в `experiments/`.

---

## Локальный запуск (разработка)

### Требования

- Docker Desktop ≥ 4.20
- 8 ГБ свободной RAM
- API-ключи: ProxyAPI, FatSecret (опционально), Telegram Bot

### Шаги

```bash
git clone https://github.com/<your-account>/Nutriclinic-Healthy-Bot.git
cd Nutriclinic-Healthy-Bot

cp .env.example .env
# заполнить TELEGRAM_BOT_TOKEN, PROXY_API_TEST_KEY и пр.

docker compose up -d --build
docker compose logs -f bot   # ждать "RAG прогрет"

# Один раз — наполнить базу знаний RAG
docker compose exec bot python /app/scripts/ingest.py
docker compose restart bot
```

В Telegram отправь `/start` своему боту.

### Полезные команды

```bash
make up           # docker compose up -d
make logs         # логи бота
make ingest       # ingest корпуса знаний
make rag-stats    # количество чанков по источникам
make costs        # стоимость API-вызовов из food_model_answer_log
```

---

## Деплой на удалённый сервер

См. **[DEPLOY.md](DEPLOY.md)** — пошаговое руководство для VPS.

Ключевое:
- **Минимум:** 4 vCPU / 3 ГБ RAM / 20 ГБ SSD
- **Рекомендуется:** 8 vCPU / 4 ГБ RAM (по §3.3 — точка перегиба ~25 одновременных пользователей)
- **Прод-конфигурация:** `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build`

---

## Разработка

### Структура веток

- `main` — продакшен-конфигурация
- Feature-ветки именуем `feat/<short-name>` или `fix/<issue>`

### Применение миграций при изменении БД

```bash
# Создать миграцию
docker compose exec bot alembic revision -m "описание"

# Применить
docker compose restart bot   # entrypoint.sh сам прогонит alembic upgrade head
```

### Перезагрузка кода без пересборки

В `docker-compose.yml` уже смонтированы `./src:/app/src` и `./alembic:/app/alembic` — правки локально подхватываются в контейнере. Достаточно:

```bash
docker compose restart bot
```

В **продакшен-конфигурации** (`docker-compose.prod.yml`) этот mount убран — код берётся из образа.

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
