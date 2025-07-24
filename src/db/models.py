from sqlalchemy import Column, Integer, String, DateTime, BigInteger, func, ARRAY, Boolean
from sqlalchemy.orm import declarative_base

Base = declarative_base()

class Table_1(Base):
    __tablename__ = "table_1"
    id = Column(Integer, primary_key=True)
