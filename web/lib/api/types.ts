export type UserOut = {
  id: string;
  username: string;
  email: string;
  role: "admin" | "editor" | "viewer" | string;
  active: boolean;
  lms_username: string | null;
  created_at: string;
};

export type UserRole = "admin" | "editor" | "viewer";

export type UserCreateInput = {
  username: string;
  email: string;
  role: UserRole;
};

export type UserUpdateInput = {
  email?: string;
  role?: UserRole;
  active?: boolean;
  lms_username?: string | null;
};

export type ApiKeyOut = {
  id: string;
  name: string;
  created_at: string;
  last_used_at: string | null;
  expires_at: string | null;
  revoked_at: string | null;
};

export type ApiKeyCreated = ApiKeyOut & {
  raw_key: string;
};

export type ApiKeyCreateInput = {
  name: string;
};

export type CoverageStats = {
  total_buildings: number;
  covered_buildings: number;
  address_offerings_count: number;
  zones_count: number;
  zones_with_polygon: number;
  zone_offerings_count: number;
  addresses_by_status: Array<{
    status: string;
    count: number;
  }>;
  top_uncovered_localities: Array<{
    locality_code: number;
    locality_name: string;
    municipality: string;
    uncovered_count: number;
  }>;
  scope: "operational" | "all";
  scope_label: string;
  scope_municipalities: string[];
};

export type CoverageStatsScope = "operational" | "all";

export type CountyOut = {
  rc_code: number;
  name: string;
};

export type MunicipalityOut = {
  rc_code: number;
  county_code: number;
  name: string;
  type: string;
};

export type LocalityOut = {
  rc_code: number;
  muni_code: number;
  name: string;
  type: string;
  type_abbr: string | null;
};

export type StreetOut = {
  rc_code: number;
  locality_code: number;
  name: string;
  full_name: string;
};

export type AddressType = "building" | "premises";
export type OfferingStatus = "available" | "planned" | "under_construction" | "unavailable";

export type AddressSearchRequest = {
  q: string;
  locality_code?: number;
  street_code?: number;
  address_type?: AddressType;
  has_point?: boolean;
  has_offering?: boolean;
  limit?: number;
};

export type AddressSearchResult = {
  rc_code: number;
  full_address: string;
  postal_code: string | null;
  address_type: string;
};

export type AddressDetail = {
  rc_code: number;
  full_address: string;
  postal_code: string | null;
  address_type: string;
  locality_code: number;
  locality_name: string;
  street_code: number | null;
  street_name: string | null;
  house_no: string;
  corpus_no: string | null;
  flat_no: string | null;
  lon: number | null;
  lat: number | null;
};

export type AddressOfferingOut = {
  id: string;
  address_code: number;
  technology_id: string;
  status: OfferingStatus;
  max_download_mbps: number;
  max_upload_mbps: number;
  status_since: string;
  planned_until: string | null;
  notes: string | null;
  created_by: string;
  created_at: string;
  updated_at: string;
};

export type AddressOfferingCreateInput = {
  technology_id: string;
  status: OfferingStatus;
  max_download_mbps: number;
  max_upload_mbps: number;
  status_since: string;
  planned_until?: string | null;
  notes?: string | null;
};

export type AddressOfferingUpdateInput = {
  status?: OfferingStatus;
  max_download_mbps?: number;
  max_upload_mbps?: number;
  status_since?: string;
  planned_until?: string | null;
  notes?: string | null;
};

export type BulkOperationOut = {
  id: string;
  user_id: string;
  username: string | null;
  operation_type: string;
  affected_count: number;
  created_at: string;
  rolled_back_at: string | null;
};

export type AddOfferingOperation = {
  type: "add_offering";
  technology_id: string;
  status: OfferingStatus;
  max_dl_mbps: number;
  max_ul_mbps: number;
  status_since: string;
  planned_until?: string | null;
  notes?: string | null;
};

export type ChangeOfferingOperation = {
  type: "change_offering";
  technology_id: string;
  new_status?: OfferingStatus;
  new_max_dl_mbps?: number;
  new_max_ul_mbps?: number;
  new_status_since?: string;
  new_planned_until?: string | null;
  new_notes?: string | null;
};

export type RemoveOfferingOperation = {
  type: "remove_offering";
  technology_id: string;
};

export type BulkOperationInput =
  | AddOfferingOperation
  | ChangeOfferingOperation
  | RemoveOfferingOperation;

export type BulkPreviewRequest = {
  operation: BulkOperationInput;
  filter: {
    locality_code?: number;
    street_codes?: number[];
    house_no_pattern?: string;
    rc_codes?: number[];
  };
};

export type BulkPreviewResponse = {
  affected_count: number;
  sample: Array<{
    address: string;
    current: Record<string, unknown> | null;
    new: Record<string, unknown>;
  }>;
  preview_token: string | null;
};

export type BulkExecuteResponse = {
  bulk_operation_id: string;
  modified_count: number;
};

export type GeoJsonGeometry = {
  type: string;
  coordinates: unknown;
};

export type GeoJsonFeature = {
  type: "Feature";
  geometry: GeoJsonGeometry | null;
  properties: Record<string, unknown>;
};

export type GeoJsonFeatureCollection = {
  type: "FeatureCollection";
  features: GeoJsonFeature[];
};

export type ZoneOut = {
  id: string;
  name: string;
  description: string | null;
  priority: number;
  has_polygon: boolean;
  polygon_geojson: Record<string, unknown> | null;
  created_at: string;
};

export type ZoneDetail = ZoneOut & {
  offerings: ZoneOfferingOut[];
  address_count: number;
};

export type ZoneOfferingOut = {
  id: string;
  zone_id: string;
  technology_id: string;
  status: OfferingStatus;
  max_download_mbps: number;
  max_upload_mbps: number;
  status_since: string;
  planned_until: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
};

export type ZoneOfferingCreateInput = {
  technology_id: string;
  status: OfferingStatus;
  max_download_mbps: number;
  max_upload_mbps: number;
  status_since: string;
  planned_until?: string | null;
  notes?: string | null;
};

export type ZoneOfferingUpdateInput = {
  status?: OfferingStatus;
  max_download_mbps?: number;
  max_upload_mbps?: number;
  status_since?: string;
  planned_until?: string | null;
  notes?: string | null;
};

export type ZoneCoverageItem = {
  zone_id: string;
  zone_name: string;
  zone_priority: number;
  offerings: ZoneOfferingOut[];
};

export type ZoneCreateInput = {
  name: string;
  description?: string | null;
  priority?: number;
  polygon_geojson?: Record<string, unknown> | null;
};

export type ZoneUpdateInput = {
  name?: string;
  description?: string | null;
  priority?: number;
  polygon_geojson?: Record<string, unknown> | null;
};

export type InPolygonResponse = {
  total: number;
  rc_codes: number[];
};

export type AuditLogOut = {
  id: number;
  user_id: string | null;
  username: string | null;
  entity_type: string;
  entity_id: string;
  action: string;
  diff: Record<string, unknown> | null;
  at: string;
};

export type TechnologyTypeOut = {
  id: string;
  code: string;
  display_name: string;
  public_name: string;
  sort_order: number;
  active: boolean;
  map_color: string;
};

export type TechnologyTypeUpdateInput = {
  display_name?: string;
  public_name?: string;
  sort_order?: number;
  active?: boolean;
  map_color?: string;
};

export type TechnologyOut = {
  id: string;
  type_id: string;
  variant_code: string;
  display_name: string;
  theoretical_max_dl_mbps: number | null;
  theoretical_max_ul_mbps: number | null;
  sort_order: number;
  active: boolean;
};

export type TechnologyCreateInput = {
  type_id: string;
  variant_code: string;
  display_name: string;
  theoretical_max_dl_mbps?: number | null;
  theoretical_max_ul_mbps?: number | null;
  sort_order?: number;
  active?: boolean;
};

export type TechnologyUpdateInput = {
  display_name?: string;
  theoretical_max_dl_mbps?: number | null;
  theoretical_max_ul_mbps?: number | null;
  sort_order?: number;
  active?: boolean;
};

// This file is intentionally kept small for bootstrap.
// Replace it with full generated types:
// npm run gen-types
