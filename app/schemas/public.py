from datetime import date

from pydantic import BaseModel


class AddressSearchResult(BaseModel):
    rc_code: int
    full_address: str
    postal_code: str | None


class PublicAddressSearchResponse(BaseModel):
    items: list[AddressSearchResult]


class AddressInfo(BaseModel):
    rc_code: int
    full_address: str
    postal_code: str | None


class AvailableTechnology(BaseModel):
    technology: str
    max_dl_mbps: int | None
    max_ul_mbps: int | None


class PlannedTechnology(BaseModel):
    technology: str
    planned_until: date | None


class AvailabilityResponse(BaseModel):
    address: AddressInfo
    available: list[AvailableTechnology]
    planned: list[PlannedTechnology]
