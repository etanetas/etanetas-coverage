import uuid
from sqlalchemy import Text, Integer, Boolean, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base


class TechnologyType(Base):
    __tablename__ = "technology_types"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(Text, unique=True)
    display_name: Mapped[str] = mapped_column(Text)
    public_name: Mapped[str] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, default=100)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Technology(Base):
    __tablename__ = "technologies"
    __table_args__ = (
        Index("idx_technologies_type", "type_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    type_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("technology_types.id"))
    variant_code: Mapped[str] = mapped_column(Text, unique=True)
    display_name: Mapped[str] = mapped_column(Text)
    theoretical_max_dl_mbps: Mapped[int | None] = mapped_column(Integer)
    theoretical_max_ul_mbps: Mapped[int | None] = mapped_column(Integer)
    sort_order: Mapped[int] = mapped_column(Integer, default=100)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
