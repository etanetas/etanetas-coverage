import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator


class PolygonGeoJSON(BaseModel):
    type: Literal["Polygon", "MultiPolygon"]
    coordinates: list  # nested list — stays loose, GeoJSON spec is recursive

# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------


class UserOut(BaseModel):
    id: uuid.UUID
    username: str
    email: str
    role: str
    active: bool
    lms_username: str | None
    created_at: datetime

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
                "username": "jdoe",
                "email": "jdoe@etanetas.lt",
                "role": "editor",
                "active": True,
                "lms_username": "jdoe_lms",
                "created_at": "2025-01-15T10:30:00Z",
            }
        },
    )


class UserCreate(BaseModel):
    username: str
    email: EmailStr
    role: Literal["admin", "editor", "viewer"]


class UserUpdate(BaseModel):
    email: EmailStr | None = None
    role: Literal["admin", "editor", "viewer"] | None = None
    active: bool | None = None
    lms_username: str | None = None


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


class AddressSearchResult(BaseModel):
    rc_code: int
    full_address: str
    postal_code: str | None
    address_type: str

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "rc_code": 12345678,
                "full_address": "Vilniaus g. 5, Šalčininkai",
                "postal_code": "17101",
                "address_type": "building",
            }
        },
    )


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
    flat_no: str | None
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


class ZoneOfferingUpdate(BaseModel):
    status: OfferingStatus | None = None
    max_download_mbps: int | None = None
    max_upload_mbps: int | None = None
    status_since: date | None = None
    planned_until: date | None = None
    notes: str | None = None


# ---------------------------------------------------------------------------
# Zones
# ---------------------------------------------------------------------------


class ZoneOut(BaseModel):
    id: uuid.UUID
    name: str
    custom_name: str | None = None
    source: str = "manual"
    description: str | None
    priority: int
    has_polygon: bool
    polygon_geojson: dict | None  # simplified GeoJSON for map rendering (may be None)
    created_at: datetime

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "b2c3d4e5-f6a7-8901-bcde-f12345678901",
                "name": "Šalčininkai miestas",
                "description": "Šalčininkai city coverage zone",
                "priority": 100,
                "has_polygon": True,
                "polygon_geojson": None,
                "created_at": "2025-01-10T08:00:00Z",
            }
        },
    )


class ZoneDetail(ZoneOut):
    """Full zone detail including offerings and address count."""
    offerings: list[ZoneOfferingOut]
    address_count: int


class ZoneCreate(BaseModel):
    name: str
    description: str | None = None
    priority: int = 100
    polygon_geojson: PolygonGeoJSON | None = None


class ZoneUpdate(BaseModel):
    name: str | None = None
    custom_name: str | None = None
    description: str | None = None
    priority: int | None = None
    polygon_geojson: PolygonGeoJSON | None = None


# ---------------------------------------------------------------------------
# Technologies
# ---------------------------------------------------------------------------


class TechnologyTypeOut(BaseModel):
    id: uuid.UUID
    code: str
    display_name: str
    public_name: str
    sort_order: int
    map_color: str

    model_config = {"from_attributes": True}


class TechnologyTypeUpdate(BaseModel):
    display_name: str | None = None
    public_name: str | None = None
    sort_order: int | None = None
    map_color: str | None = None


class TechnologyOut(BaseModel):
    id: uuid.UUID
    type_id: uuid.UUID
    variant_code: str
    display_name: str
    theoretical_max_dl_mbps: int | None
    theoretical_max_ul_mbps: int | None
    sort_order: int

    model_config = {"from_attributes": True}


class TechnologyCreate(BaseModel):
    type_id: uuid.UUID
    variant_code: str
    display_name: str
    theoretical_max_dl_mbps: int | None = None
    theoretical_max_ul_mbps: int | None = None
    sort_order: int = 100


class TechnologyUpdate(BaseModel):
    display_name: str | None = None
    theoretical_max_dl_mbps: int | None = None
    theoretical_max_ul_mbps: int | None = None
    sort_order: int | None = None


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
        return not any(
            [self.locality_code, self.street_codes, self.house_no_pattern, self.rc_codes]
        )

    @model_validator(mode="after")
    def _require_scope(self):
        if not self.rc_codes and self.locality_code is None:
            raise ValueError(
                "Either rc_codes or locality_code is required (prevents nation-wide updates)"
            )
        return self


class AddOfferingOperation(BaseModel):
    type: Literal["add_offering"]
    technology_id: uuid.UUID
    status: OfferingStatus
    max_dl_mbps: int
    max_ul_mbps: int
    status_since: date
    planned_until: date | None = None
    notes: str | None = None


class ChangeOfferingOperation(BaseModel):
    """Update existing address_offerings for a given technology. Any field left None is not changed."""
    type: Literal["change_offering"]
    technology_id: uuid.UUID
    new_status: OfferingStatus | None = None
    new_max_dl_mbps: int | None = None
    new_max_ul_mbps: int | None = None
    new_status_since: date | None = None
    new_planned_until: date | None = None  # to clear, use sentinel string "null" — see _execute
    new_notes: str | None = None


class RemoveOfferingOperation(BaseModel):
    """Delete address_offerings for a given technology from filtered addresses."""
    type: Literal["remove_offering"]
    technology_id: uuid.UUID


BulkOperation = Annotated[
    AddOfferingOperation | ChangeOfferingOperation | RemoveOfferingOperation,
    Field(discriminator="type"),
]


class BulkPreviewRequest(BaseModel):
    operation: BulkOperation
    filter: BulkFilter


class BulkSampleItem(BaseModel):
    address: str
    current: dict | None
    new: dict


class BulkPreviewResponse(BaseModel):
    affected_count: int
    sample: list[BulkSampleItem]
    preview_token: str | None
    expires_at: datetime | None = None

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "affected_count": 42,
                "sample": [
                    {
                        "address": "Vilniaus g. 5, Šalčininkai",
                        "current": None,
                        "new": {"status": "available", "max_dl_mbps": 100, "max_ul_mbps": 50},
                    }
                ],
                "preview_token": "tmp_abc123def456",
                "expires_at": "2025-01-15T10:35:00Z",
            }
        },
    )


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


class BulkOperationDetailOut(BulkOperationOut):
    filter_criteria: dict | None = None


class BulkRollbackResponse(BaseModel):
    rolled_back_count: int


class AuditLogOut(BaseModel):
    id: int  # internal serial — treat as opaque; do not rely on ordering
    user_id: uuid.UUID | None
    username: str | None
    entity_type: str
    entity_id: str
    action: str
    diff: dict | None
    at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Coverage statistics (used by admin/stats.py)
# ---------------------------------------------------------------------------


class StatusBreakdown(BaseModel):
    status: str
    count: int


class UncoveredLocality(BaseModel):
    locality_code: int
    locality_name: str
    municipality: str
    uncovered_count: int


class CoverageStats(BaseModel):
    total_buildings: int
    covered_buildings: int
    address_offerings_count: int
    zones_count: int
    zones_with_polygon: int
    zone_offerings_count: int
    addresses_by_status: list[StatusBreakdown]
    top_uncovered_localities: list[UncoveredLocality]
    scope: str
    scope_label: str
    scope_municipalities: list[str]
