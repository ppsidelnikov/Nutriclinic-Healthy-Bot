up:
	docker compose up --build

up-d:
	docker compose up --build -d

down:
	docker compose down

down-v:
	docker compose down -v

logs:
	docker compose logs -f

restart:
	docker compose up --build -d --force-recreate

clear-cache:
	docker compose exec redis redis-cli FLUSHDB

status:
	@echo "=== PostgreSQL ==="
	@docker compose exec postgres psql -U postgres -d healthy_bot_prod -c "\dt"
	@docker compose exec postgres psql -U postgres -d healthy_bot_prod -c "SELECT 'message_log' as table, COUNT(*) FROM message_log UNION ALL SELECT 'food_model_answer_log', COUNT(*) FROM food_model_answer_log UNION ALL SELECT 'ingredients', COUNT(*) FROM ingredients;"
	@echo "=== Redis ==="
	@docker compose exec redis redis-cli DBSIZE
	@docker compose exec redis redis-cli KEYS "fatsecret:*"

ingest:
	docker compose exec bot python /app/scripts/ingest.py $(ARGS)

ingest-clear:
	docker compose exec bot python /app/scripts/ingest.py --clear

rag-stats:
	docker compose exec postgres psql -U dbuser -d healthy_bot_prod -c "SELECT source, COUNT(*) as chunks FROM knowledge_chunks GROUP BY source ORDER BY chunks DESC;"

costs:
	docker compose exec postgres psql -U dbuser -d healthy_bot_prod -c "\
SELECT model_name, COUNT(*) AS запросов, \
SUM(token_input) AS токенов_вход, SUM(token_output) AS токенов_выход, \
ROUND(SUM(request_price)::numeric,4) AS руб_итого, \
ROUND(AVG(request_price)::numeric,4) AS руб_среднее \
FROM food_model_answer_log GROUP BY model_name ORDER BY руб_итого DESC;"

costs-daily:
	docker compose exec postgres psql -U dbuser -d healthy_bot_prod -c "\
SELECT DATE(created_at) AS день, model_name, COUNT(*) AS запросов, \
ROUND(SUM(request_price)::numeric,4) AS руб \
FROM food_model_answer_log WHERE created_at IS NOT NULL \
GROUP BY день, model_name ORDER BY день DESC, руб DESC;"

costs-detail:
	docker compose exec postgres psql -U dbuser -d healthy_bot_prod -c "\
SELECT id, created_at, model_name, token_input, token_output, \
ROUND(request_price::numeric,4) AS руб, \
LEFT(payload_json::text, 100) AS payload \
FROM food_model_answer_log ORDER BY id DESC LIMIT 20;"

.PHONY: up up-d down down-v logs restart ingest ingest-clear rag-stats costs costs-daily costs-detail


