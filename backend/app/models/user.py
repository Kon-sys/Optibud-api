import uuid
from sqlalchemy import Column, String, BigInteger, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from app.models.base import Base, JSONType

class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email_normalized = Column(String(254), unique=True, nullable=False)
    display_name = Column(String(80), nullable=False)
    password_hash = Column(String, nullable=False)
    locale = Column(String(10), nullable=False, default="ru")
    notification_preferences = Column(JSONType, nullable=False, default=dict)
    terms_version = Column(String(50), nullable=True)
    terms_accepted_at = Column(DateTime(timezone=True), nullable=True)
    verified_at = Column(DateTime(timezone=True), nullable=True)
    status = Column(String(20), nullable=False, default="active")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    version = Column(BigInteger, nullable=False, default=1)
