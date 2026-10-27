import uuid

from sqlalchemy import BigInteger, CheckConstraint, Column, DateTime, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import UUID

from app.core.utils import utcnow
from app.models.base import Base, in_list
from app.models.enums import InvitationStatus


class Invitation(Base):
    __tablename__ = "invitations"
    __table_args__ = (CheckConstraint(in_list("status", InvitationStatus), name="ck_invitations_status"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    household_id = Column(UUID(as_uuid=True), ForeignKey("households.id"), nullable=False, index=True)
    email_normalized = Column(String(254), nullable=False)
    token_hash = Column(String(64), unique=True, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    status = Column(String(20), nullable=False, default=InvitationStatus.PENDING.value)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    accepted_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    version = Column(BigInteger, nullable=False, default=1)


_PENDING = text("status = 'pending'")

Index(
    "uq_invitations_pending_pair",
    Invitation.household_id,
    Invitation.email_normalized,
    unique=True,
    postgresql_where=_PENDING,
    sqlite_where=_PENDING,
)
