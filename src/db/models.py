from sqlalchemy import Column, Integer, String, DateTime, BigInteger, Numeric, ARRAY, Boolean, UniqueConstraint, Text, JSON, Index
from sqlalchemy.orm import declarative_base
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

# FatSecret API Cache Models
class FatSecretSearchCache(Base):
    __tablename__ = "fatsecret_search_cache"
    __table_args__ = (
        Index('idx_search_query', 'search_query'),
        Index('idx_search_type', 'search_type'),
        Index('idx_created_at', 'created_at'),
    )
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    search_query = Column(String(500), nullable=False)  # The search term used
    search_type = Column(String(50), nullable=False)    # 'dish_name' or 'ingredient'
    max_results = Column(Integer, nullable=False, default=5)
    api_response = Column(JSON, nullable=False)         # Full API response JSON
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=True)       # Optional expiration date
    
    def __repr__(self):
        return f"<FatSecretSearchCache(query='{self.search_query}', type='{self.search_type}')>"

class FatSecretFoodCache(Base):
    __tablename__ = "fatsecret_food_cache"
    __table_args__ = (
        Index('idx_food_id', 'fatsecret_food_id'),
        Index('idx_food_name', 'food_name'),
        Index('idx_brand_name', 'brand_name'),
    )
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    fatsecret_food_id = Column(String(100), nullable=False, unique=True)  # FatSecret's food ID
    food_name = Column(String(500), nullable=False)
    brand_name = Column(String(200), nullable=True)
    food_description = Column(Text, nullable=True)      # Raw description from API
    food_type = Column(String(100), nullable=True)      # Type of food
    food_url = Column(String(1000), nullable=True)     # FatSecret URL
    
    # Parsed nutritional values per 100g
    calories_per_100g = Column(Numeric(10, 3), nullable=True)
    protein_per_100g = Column(Numeric(10, 3), nullable=True)
    fat_per_100g = Column(Numeric(10, 3), nullable=True)
    carbs_per_100g = Column(Numeric(10, 3), nullable=True)
    
    # Raw API data
    raw_api_data = Column(JSON, nullable=True)         # Full food object from API
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    def __repr__(self):
        return f"<FatSecretFoodCache(id='{self.fatsecret_food_id}', name='{self.food_name}')>"

    
