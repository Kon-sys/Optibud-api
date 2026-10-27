import uuid

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID

from app.core.utils import utcnow
from app.models.base import Base, JSONType, in_list
from app.models.enums import TokenPurpose


class UserToken(Base):


    __tablename__ = "user_tokens"
    __table_args__ = (CheckConstraint(in_list("purpose", TokenPurpose), name="ck_user_tokens_purpose"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    purpose = Column(String(30), nullable=False)
    token_hash = Column(String(64), unique=True, nullable=False)
    payload = Column(JSONType, nullable=True)  # например {"new_email": "..."}
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
