import uuid

from sqlalchemy import BigInteger, Column, ForeignKey
from sqlalchemy.dialects.postgresql import UUID

from app.models.base import Base


class ForecastCategory(Base):
    """Разбивка прогноза по категориям; сумма должна совпадать с Forecast.predicted_minor."""

    __tablename__ = "forecast_categories"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    forecast_id = Column(UUID(as_uuid=True), ForeignKey("forecasts.id", ondelete="CASCADE"), nullable=False, index=True)
    category_id = Column(UUID(as_uuid=True), ForeignKey("categories.id"), nullable=False)
    predicted_minor = Column(BigInteger, nullable=False)
    lower_minor = Column(BigInteger, nullable=True)
    upper_minor = Column(BigInteger, nullable=True)
