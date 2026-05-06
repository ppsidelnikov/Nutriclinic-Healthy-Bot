FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Предзагружаем cross-encoder в образ, чтобы не качать ~120 МБ при старте контейнера.
# После этого rag_warmup() в on_startup загружает модель из локального кэша за ~3 сек.
RUN python -c "from sentence_transformers import CrossEncoder; \
               CrossEncoder('cross-encoder/mmarco-mMiniLMv2-L12-H384-v1')"

COPY . .

RUN chmod +x /app/entrypoint.sh

ENV PYTHONPATH=/app/src
ENV ENV_PATH=/app/.env
# Используем кэш HuggingFace (модель скачана выше) без сетевых HEAD-проверок
ENV HF_HUB_OFFLINE=1
ENV TRANSFORMERS_OFFLINE=1

WORKDIR /app/src

ENTRYPOINT ["/app/entrypoint.sh"]
