import uuid
from datetime import date, datetime

from geoalchemy2 import Geometry
from sqlalchemy import (
    TIMESTAMP,
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ServiceZone(Base):
    __tablename__ = "service_zones"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    polygon: Mapped[str | None] = mapped_column(Geometry("MULTIPOLYGON", srid=4326))
    priority: Mapped[int] = mapped_column(Integer, default=100)
    source: Mapped[str] = mapped_column(Text, default="manual", server_default="manual")
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, default=datetime.now)
    updated_at: Mapped[datetime | None] = mapped_column(TIMESTAMP, onupdate=datetime.now)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ZoneOffering(Base):
    __tablename__ = "zone_offerings"
    __table_args__ = (
        CheckConstraint("status IN ('available', 'planned', 'under_construction', 'unavailable')", name='ck_zone_offerings_status'),
        UniqueConstraint("zone_id", "technology_id"),
        Index("idx_zone_offerings_zone", "zone_id"),
        Index("idx_zone_offerings_tech", "technology_id"),
        Index("idx_zone_offerings_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    zone_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("service_zones.id", ondelete="CASCADE"))
    technology_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("technologies.id"))
    status: Mapped[str] = mapped_column(Text)
    max_download_mbps: Mapped[int] = mapped_column(Integer)
    max_upload_mbps: Mapped[int] = mapped_column(Integer)
    status_since: Mapped[date] = mapped_column(Date)
    planned_until: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP, default=datetime.now, onupdate=datetime.now)


class AddressOffering(Base):
    __tablename__ = "address_offerings"
    __table_args__ = (
        CheckConstraint("status IN ('available', 'planned', 'under_construction', 'unavailable')", name='ck_address_offerings_status'),
        UniqueConstraint("address_code", "technology_id"),
        Index("idx_address_offerings_addr", "address_code"),
        Index("idx_address_offerings_tech", "technology_id"),
        Index("idx_address_offerings_status", "status"),
        Index("idx_address_offerings_bulk", "bulk_operation_id"),
        Index(
            "idx_address_offerings_tech_available",
            "technology_id",
            postgresql_where=text("status = 'available'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    address_code: Mapped[int] = mapped_column(BigInteger, ForeignKey("addresses.rc_code"))
    technology_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("technologies.id"))
    status: Mapped[str] = mapped_column(Text)
    max_download_mbps: Mapped[int] = mapped_column(Integer)
    max_upload_mbps: Mapped[int] = mapped_column(Integer)
    status_since: Mapped[date] = mapped_column(Date)
    planned_until: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    bulk_operation_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("bulk_operations.id"))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP, default=datetime.now, onupdate=datetime.now)
