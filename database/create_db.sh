# Путь к .env файлу в директории src
#!/usr/bin/env bash
ENV_FILE="src/.env"

# Проверка существования .env файла
if [ ! -f "$ENV_FILE" ]; then
    echo "Ошибка: файл $ENV_FILE не найден!"
    exit 1
fi

# Загрузка переменных из .env файла
echo "Загрузка переменных из $ENV_FILE..."
. "$ENV_FILE"

# Проверка наличия необходимых переменных
if [ -z "$DB_NAME" ] || [ -z "$DB_USER" ] || [ -z "$DB_PASSWORD" ]; then
    echo "Ошибка: необходимо указать DB_NAME, DB_USER и DB_PASSWORD в файле $ENV_FILE!"
    exit 1
fi

# Вывод информации о создаваемой базе
echo "Создание базы данных $DB_NAME для пользователя $DB_USER..."

PG_SUPERUSER=${PG_SUPERUSER:-postgres}

if [ "$PG_SUPERUSER" = "postgres" ]; then
  PSQ="sudo -u postgres psql"
else
  PSQ="psql -U $PG_SUPERUSER"
fi

$PSQ -d postgres \
  -v db_name="$DB_NAME" \
  -v db_user="$DB_USER" \
  -v db_password="'$DB_PASSWORD'" \
  -f "database/init_db.sql"

# Проверка успешности выполнения
if [ $? -eq 0 ]; then
    echo "База данных успешно создана!"
    echo "База: $DB_NAME"
    echo "Пользователь: $DB_USER"
else
    echo "Ошибка при создании базы данных!"
fi