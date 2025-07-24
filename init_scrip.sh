# Цвета для вывода
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Функция для вывода сообщений с форматированием
log() {
  echo -e "${GREEN}[$(date +'%Y-%m-%d %H:%M:%S')] $1${NC}"
}

error() {
  echo -e "${RED}[$(date +'%Y-%m-%d %H:%M:%S')] ОШИБКА: $1${NC}"
}

warning() {
  echo -e "${YELLOW}[$(date +'%Y-%m-%d %H:%M:%S')] ВНИМАНИЕ: $1${NC}"
}

# Функция проверки успешности выполнения последней команды
check_result() {
  if [ $? -ne 0 ]; then
    error "$1"
    exit 1
  fi
}

# Обновление системы
log "Начинаем настройку сервера..."
log "Обновление списка пакетов..."
apt-get update
check_result "Не удалось обновить список пакетов"

log "Обновление установленных пакетов..."
apt-get -y upgrade
check_result "Не удалось обновить пакеты"

# Установка базовых инструментов
log "Установка базовых инструментов разработки..."
apt-get install -y build-essential wget curl git unzip software-properties-common
check_result "Не удалось установить базовые инструменты"

# Установка Python и инструментов для Python
log "Установка Python и связанных инструментов..."
apt-get install -y python3 python3-pip python3-dev python3-venv
check_result "Не удалось установить Python"

# Установка Poetry (современный менеджер пакетов для Python)
log "Установка Poetry..."
curl -sSL https://install.python-poetry.org | python3 -
check_result "Не удалось установить Poetry"

# Добавление Poetry в PATH
export PATH="/root/.local/bin:$PATH"
echo 'export PATH="/root/.local/bin:$PATH"' >> ~/.bashrc
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc

# Установка PostgreSQL
log "Установка PostgreSQL..."
apt-get install -y postgresql postgresql-contrib
check_result "Не удалось установить PostgreSQL"

# Запуск PostgreSQL
log "Запуск сервиса PostgreSQL..."
systemctl start postgresql
systemctl enable postgresql
check_result "Не удалось запустить PostgreSQL"

# Запускаем скрипт с инициализацией базы данных
log "Инициализация БД"
database/create_db.sh
check_result "Не удалось инициализировать БД"