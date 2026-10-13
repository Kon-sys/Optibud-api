import uuid
from sqlalchemy import Column, String, Integer, BigInteger, Date, ForeignKey, Boolean, DateTime, Enum as PgEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from core.database import Base

class Category(Base):
    __tablename__ = "categories"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    household_id = Column(UUID(as_uuid=True), ForeignKey("households.id"), nullable=True) # null для системных
    parent_id = Column(UUID(as_uuid=True), ForeignKey("categories.id"), nullable=True)
    system_code = Column(String(50), unique=True, nullable=True)
    name = Column(String(80), nullable=False)
    type = Column(String(20), nullable=False) # income, expense
    is_archived = Column(Boolean, nullable=False, default=False)
    version = Column(BigInteger, nullable=False, default=1)