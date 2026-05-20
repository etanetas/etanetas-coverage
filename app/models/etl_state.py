from datetime import datetime

from sqlalchemy import TIMESTAMP, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class EtlState(Base):
    __tablename__ = "etl_state"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP)
