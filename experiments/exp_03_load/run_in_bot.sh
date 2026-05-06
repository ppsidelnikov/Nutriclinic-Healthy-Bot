#!/bin/bash
# Запускает load_test.py ВНУТРИ контейнера бота.
# Так ресурсные замеры через docker stats будут отражать реальную нагрузку.
#
# Использование:
#   ./run_in_bot.sh L1 5 60          # label, users, duration
#   ./run_in_bot.sh L1 50 180

set -e

LABEL="${1:-L1}"
USERS="${2:-5}"
DURATION="${3:-60}"

echo "==> Запуск нагрузочника внутри nutriclinic_bot: label=$LABEL, users=$USERS, duration=$DURATION"

docker compose exec -T bot python /app/experiments/exp_03_load/load_test.py \
    --scenario "${LABEL}_n${USERS}" \
    --users "$USERS" \
    --duration "$DURATION" \
    --ramp 10 \
    --every 8.0
