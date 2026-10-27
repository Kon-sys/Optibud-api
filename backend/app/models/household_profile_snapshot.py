import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID

from app.core.utils import utcnow
from app.models.base import Base


class HouseholdProfileSnapshot(Base):


    __tablename__ = "household_profile_snapshots"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    household_id = Column(UUID(as_uuid=True), ForeignKey("households.id"), nullable=False, index=True)
    adults_count = Column(Integer, nullable=False)
    children_count = Column(Integer, nullable=False)
    region_code = Column(String(50), nullable=True)
    income_band = Column(String(50), nullable=True)
    valid_from = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    valid_to = Column(DateTime(timezone=True), nullable=True)
