from sqlalchemy import Column, Integer, BigInteger, String, DateTime, Numeric, Float, UniqueConstraint, JSON, func
from sqlalchemy.orm import declarative_base
from pgvector.sqlalchemy import Vector
from datetime import datetime

Base = declarative_base()


class MessageLog(Base):
    __tablename__ = "message_log"
    id = Column(Integer, primary_key=True)
    chat_id = Column(String, nullable=True)
    user_id = Column(String, nullable=True)
    user_name = Column(String, nullable=True)
    user_nickname = Column(String, nullable=True)
    message_dttm = Column(String, nullable=True)
    message_txt = Column(String, nullable=True)
    message_content = Column(String, nullable=True)
    message_id = Column(String, nullable=True)


class FoodModelAnswerLog(Base):
    __tablename__ = "food_model_answer_log"
    id = Column(Integer, primary_key=True)
    chat_id = Column(String, nullable=True)
    message_id = Column(String, nullable=True)
    model_name = Column(String, nullable=True)
    model_answer = Column(String, nullable=True)
    token_input = Column(Integer, nullable=True)
    token_output = Column(Integer, nullable=True)
    payload_json = Column(JSON, nullable=True)
    request_price = Column(Numeric(12, 6), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=True)


EMBEDDING_DIM = 1536  # text-embedding-3-small


class KnowledgeChunk(Base):
    """Чанки базы знаний по нутрициологии с векторными эмбеддингами."""
    __tablename__ = "knowledge_chunks"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    source      = Column(String, nullable=False)        # имя файла-источника
    chunk_index = Column(Integer, nullable=False)       # порядковый номер чанка в документе
    text        = Column(String, nullable=False)        # текст чанка
    embedding   = Column(Vector(EMBEDDING_DIM), nullable=True)
    created_at  = Column(DateTime, default=datetime.utcnow, nullable=False)


class ChatMessage(Base):
    """Персистентное хранилище всех сообщений диалога (долгосрочная память)."""
    __tablename__ = "chat_messages"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    chat_id    = Column(String, nullable=False, index=True)
    role       = Column(String, nullable=False)   # user / assistant
    text       = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class UserProfile(Base):
    __tablename__ = "user_profile"

    id = Column(Integer, primary_key=True, autoincrement=True)
    telegram_id = Column(String, nullable=False, unique=True, index=True)
    name = Column(String, nullable=True)
    age = Column(Integer, nullable=True)
    gender = Column(String, nullable=True)          # male / female
    weight_kg = Column(Numeric(5, 1), nullable=True)
    height_cm = Column(Numeric(5, 1), nullable=True)
    goal = Column(String, nullable=True)            # weight_loss / muscle_gain / maintain
    daily_calories_target = Column(Integer, nullable=True)
    restrictions = Column(String, nullable=True)    # аллергии, запреты
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class Ingredient(Base):
    __tablename__ = "ingredients"
    __table_args__ = (
        UniqueConstraint("name_normalized", name="uq_ingredient_name_normalized"),
    )
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    name_normalized = Column(String, nullable=False, unique=True)
    calories_kcal = Column(Numeric(10, 3), nullable=True)
    protein_g = Column(Numeric(10, 3), nullable=True)
    fat_g = Column(Numeric(10, 3), nullable=True)
    carbs_g = Column(Numeric(10, 3), nullable=True)


class WeightLog(Base):
    """Журнал веса пользователя — несколько записей за день допускаются,
    последняя считается текущим весом."""
    __tablename__ = "weight_log"

    id           = Column(BigInteger, primary_key=True)
    telegram_id  = Column(String, nullable=False, index=True)
    weight_kg    = Column(Float, nullable=False)
    recorded_at  = Column(DateTime, nullable=False, server_default=func.now())


class FoodDiary(Base):
    """Дневник питания пользователя — записи о съеденном, разбитые по приёмам пищи."""
    __tablename__ = "food_diary"

    id           = Column(BigInteger, primary_key=True)
    telegram_id  = Column(String, nullable=False, index=True)
    eaten_at     = Column(DateTime, nullable=False, server_default=func.now())
    meal_type    = Column(String(20), nullable=False)   # breakfast / lunch / dinner / snack
    dish_name    = Column(String, nullable=False)
    portion_g    = Column(Float, nullable=True)
    kcal         = Column(Float, nullable=False)
    protein_g    = Column(Float, nullable=True)
    fat_g        = Column(Float, nullable=True)
    carbs_g      = Column(Float, nullable=True)
    source       = Column(String(20), nullable=False, server_default="photo")  # photo / manual
    created_at   = Column(DateTime, nullable=False, server_default=func.now())

