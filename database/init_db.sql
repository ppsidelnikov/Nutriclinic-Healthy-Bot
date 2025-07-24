-- Установка переменных (они будут переданы при запуске скрипта)
\set db_name :db_name
\set db_user :db_user
\set db_password :db_password

-- Создание базы данных
CREATE DATABASE :"db_name";

-- Создание пользователя с паролем
CREATE USER :"db_user" WITH PASSWORD :'db_password';

-- Подключение к созданной базе данных
\c :"db_name"

-- Предоставление всех прав пользователю на базу данных
GRANT ALL PRIVILEGES ON DATABASE :"db_name" TO :"db_user";

-- Предоставление прав на схему public (необходимо для полного доступа)
GRANT ALL ON SCHEMA public TO :"db_user";

-- Предоставление прав на все будущие таблицы
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO :"db_user";
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO :"db_user";
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON FUNCTIONS TO :"db_user";

-- Вывод информации об успешном создании
\echo 'База данных создана: ' :db_name
\echo 'Пользователь создан: ' :db_user
\echo 'С паролем: ' :db_password