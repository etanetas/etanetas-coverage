from app.models.base import Base
from datetime import datetime
from sqlalchemy import Text, TIMESTAMP, BigInteger, ForeignKey, Index, text
from geoalchemy2 import Geometry
from sqlalchemy.orm import Mapped, mapped_column


class County(Base):
    __tablename__ = "counties"

    rc_code: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    synced_at: Mapped[datetime] = mapped_column(TIMESTAMP, default=datetime.now)


class Municipality(Base):
    __tablename__ = "municipalities"
    __table_args__ = (
        Index("idx_municipalities_county", "county_code"),
    )

    rc_code: Mapped[int] = mapped_column(primary_key=True)
    county_code: Mapped[int] = mapped_column(ForeignKey("counties.rc_code"))
    name: Mapped[str] = mapped_column(Text)
    type: Mapped[str] = mapped_column(Text)
    synced_at: Mapped[datetime] = mapped_column(TIMESTAMP, default=datetime.now)


class Locality(Base):
    __tablename__ = "localities"
    __table_args__ = (
        Index("idx_localities_muni", "muni_code"),
        Index("idx_localities_name_trgm", "name", postgresql_using="gin", postgresql_ops={"name": "gin_trgm_ops"}),
    )

    rc_code: Mapped[int] = mapped_column(primary_key=True)
    muni_code: Mapped[int] = mapped_column(ForeignKey("municipalities.rc_code"))
    name: Mapped[str] = mapped_column(Text)
    type: Mapped[str] = mapped_column(Text)
    boundary: Mapped[str | None] = mapped_column(Geometry("MULTIPOLYGON", srid=4326))
    synced_at: Mapped[datetime] = mapped_column(TIMESTAMP, default=datetime.now)


class Street(Base):
    __tablename__ = "streets"
    __table_args__ = (
        Index("idx_streets_locality", "locality_code"),
        Index("idx_streets_full_name_trgm", "full_name", postgresql_using="gin", postgresql_ops={"full_name": "gin_trgm_ops"}),
    )

    rc_code: Mapped[int] = mapped_column(primary_key=True)
    locality_code: Mapped[int] = mapped_column(ForeignKey("localities.rc_code"))
    name: Mapped[str] = mapped_column(Text)
    full_name: Mapped[str] = mapped_column(Text)
    axis: Mapped[str | None] = mapped_column(Geometry("MULTILINESTRING", srid=4326))
    synced_at: Mapped[datetime] = mapped_column(TIMESTAMP, default=datetime.now)


class Address(Base):
    __tablename__ = "addresses"
    __table_args__ = (
        Index("idx_addresses_house_no_trgm", "house_no", postgresql_using="gin", postgresql_ops={"house_no": "gin_trgm_ops"}),
        Index("idx_addresses_street", "street_code", postgresql_where=text("deleted_at IS NULL")),
        Index("idx_addresses_locality", "locality_code", postgresql_where=text("deleted_at IS NULL")),
    )

    rc_code: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    street_code: Mapped[int | None] = mapped_column(ForeignKey("streets.rc_code"))
    locality_code: Mapped[int] = mapped_column(ForeignKey("localities.rc_code"))
    house_no: Mapped[str] = mapped_column(Text)
    postal_code: Mapped[str | None] = mapped_column(Text)
    point: Mapped[str | None] = mapped_column(Geometry("POINT", srid=4326))
    synced_at: Mapped[datetime] = mapped_column(TIMESTAMP, default=datetime.now)
    deleted_at: Mapped[datetime | None] = mapped_column(TIMESTAMP)
