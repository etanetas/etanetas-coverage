import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, EmailStr, Field

# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

class UserOut(BaseModel):
    id: uuid.UUID
    username: str
    email: str
    role: str
    active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class UserCreate(BaseModel):
    username: str
    email: EmailStr
    role: Literal["admin", "editor", "viewer"]


class UserUpdate(BaseModel):
    email: EmailStr | None = None
    role: Literal["admin", "editor", "viewer"] | None = None
    active: bool | None = None


class ApiKeyOut(BaseModel):
    id: uuid.UUID
    name: str
    created_at: datetime
    last_used_at: datetime | None
    expires_at: datetime | None
    revoked_at: datetime | None

    model_config = {"from_attributes": True}


class ApiKeyCreate(BaseModel):
    name: str = "default"


class ApiKeyCreated(ApiKeyOut):
    raw_key: str


# ---------------------------------------------------------------------------
# Addresses (admin — read-only, offerings are editable)
# ---------------------------------------------------------------------------

class AddressSearchRequest(BaseModel):
    q: str
    locality_code: int | None = None
    street_code: int | None = None
    address_type: Literal["building", "premises"] | None = None
    limit: Annotated[int, Field(ge=1, le=100)] = 20


class AddressSearchResult(BaseModel):
    rc_code: int
    full_address: str
    postal_code: str | None
    address_type: str


class AddressDetail(BaseModel):
    rc_code: int
    full_address: str
    postal_code: str | None
    address_type: str
    locality_code: int
    locality_name: str
    street_code: int | None
    street_name: str | None
    house_no: str
    corpus_no: str | None
    lon: float | None
    lat: float | None


# ---------------------------------------------------------------------------
# Offerings (shared)
# ---------------------------------------------------------------------------

OfferingStatus = Literal["available", "planned", "under_construction", "unavailable"]


class OfferingBase(BaseModel):
    technology_id: uuid.UUID
    status: OfferingStatus
    max_download_mbps: int
    max_upload_mbps: int
    status_since: date
    planned_until: date | None = None
    notes: str | None = None


class AddressOfferingOut(OfferingBase):
    id: uuid.UUID
    address_code: int
    created_by: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AddressOfferingCreate(OfferingBase):
    pass


class AddressOfferingUpdate(BaseModel):
    status: OfferingStatus | None = None
    max_download_mbps: int | None = None
    max_upload_mbps: int | None = None
    status_since: date | None = None
    planned_until: date | None = None
    notes: str | None = None


class ZoneOfferingOut(OfferingBase):
    id: uuid.UUID
    zone_id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ZoneOfferingCreate(OfferingBase):
    pass


# ---------------------------------------------------------------------------
# Zones
# ---------------------------------------------------------------------------

class ZoneOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    priority: int
    has_polygon: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class ZoneCreate(BaseModel):
    name: str
    description: str | None = None
    priority: int = 100
    polygon_geojson: dict | None = None


class ZoneUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    priority: int | None = None
    polygon_geojson: dict | None = None


# ---------------------------------------------------------------------------
# Technologies
# ---------------------------------------------------------------------------

class TechnologyTypeOut(BaseModel):
    id: uuid.UUID
    code: str
    display_name: str
    public_name: str
    sort_order: int
    active: bool

    model_config = {"from_attributes": True}


class TechnologyTypeUpdate(BaseModel):
    display_name: str | None = None
    public_name: str | None = None
    sort_order: int | None = None
    active: bool | None = None


class TechnologyOut(BaseModel):
    id: uuid.UUID
    type_id: uuid.UUID
    variant_code: str
    display_name: str
    theoretical_max_dl_mbps: int | None
    theoretical_max_ul_mbps: int | None
    sort_order: int
    active: bool

    model_config = {"from_attributes": True}


class TechnologyCreate(BaseModel):
    type_id: uuid.UUID
    variant_code: str
    display_name: str
    theoretical_max_dl_mbps: int | None = None
    theoretical_max_ul_mbps: int | None = None
    sort_order: int = 100
    active: bool = True


class TechnologyUpdate(BaseModel):
    display_name: str | None = None
    theoretical_max_dl_mbps: int | None = None
    theoretical_max_ul_mbps: int | None = None
    sort_order: int | None = None
    active: bool | None = None


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Bulk operations
# ---------------------------------------------------------------------------

class BulkFilter(BaseModel):
    locality_code: int | None = None
    street_codes: list[int] | None = None
    house_no_pattern: str | None = None
    rc_codes: list[int] | None = None

    def is_empty(self) -> bool:
        return not any([self.locality_code, self.street_codes, self.house_no_pattern, self.rc_codes])


class AddOfferingOperation(BaseModel):
    type: Literal["add_offering"]
    technology_id: uuid.UUID
    status: OfferingStatus
    max_dl_mbps: int
    max_ul_mbps: int
    status_since: date
    planned_until: date | None = None
    notes: str | None = None


class BulkPreviewRequest(BaseModel):
    operation: AddOfferingOperation
    filter: BulkFilter


class BulkSampleItem(BaseModel):
    address: str
    current: dict | None
    new: dict


class BulkPreviewResponse(BaseModel):
    affected_count: int
    sample: list[BulkSampleItem]
    preview_token: str | None


class BulkExecuteRequest(BaseModel):
    preview_token: str


class BulkExecuteResponse(BaseModel):
    bulk_operation_id: uuid.UUID
    modified_count: int


class BulkOperationOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    username: str | None
    operation_type: str
    affected_count: int
    created_at: datetime
    rolled_back_at: datetime | None

    model_config = {"from_attributes": True}


class AuditLogOut(BaseModel):
    id: int
    user_id: uuid.UUID | None
    username: str | None
    entity_type: str
    entity_id: str
    action: str
    diff: dict | None
    at: datetime

    model_config = {"from_attributes": True}
