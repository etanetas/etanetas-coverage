import type {
  AddressDetail,
  AddressOfferingCreateInput,
  AddressOfferingOut,
  AddressOfferingUpdateInput,
  AddressSearchRequest,
  AddressSearchResult,
  ApiKeyCreated,
  ApiKeyCreateInput,
  ApiKeyOut,
  AuditLogOut,
  BulkExecuteResponse,
  BulkOperationInput,
  BulkOperationOut,
  BulkPreviewResponse,
  CountyOut,
  CoverageStats,
  CoverageStatsScope,
  GeoJsonFeatureCollection,
  InPolygonResponse,
  LocalityOut,
  MunicipalityOut,
  StreetOut,
  TechnologyCreateInput,
  TechnologyOut,
  TechnologyTypeOut,
  TechnologyTypeUpdateInput,
  TechnologyUpdateInput,
  UserCreateInput,
  UserOut,
  UserUpdateInput,
  ZoneCoverageItem,
  ZoneCreateInput,
  ZoneDetail,
  ZoneOfferingCreateInput,
  ZoneOfferingOut,
  ZoneOfferingUpdateInput,
  ZoneOut,
  ZoneUpdateInput,
} from "@/lib/api/types";
import { useAuthStore } from "@/lib/stores/auth";

type RequestOptions = {
  method?: "GET" | "POST" | "PUT" | "DELETE";
  body?: unknown;
  signal?: AbortSignal;
};

export class ApiError extends Error {
  readonly status: number;
  readonly detail: string;

  constructor(status: number, detail: string) {
    super(detail);
    this.status = status;
    this.detail = detail;
  }
}

export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { apiKey, apiUrl } = useAuthStore.getState();
  if (!apiKey) {
    throw new ApiError(401, "Brak API key. Przejdź do konfiguracji.");
  }

  const response = await fetch(`${apiUrl}${path}`, {
    method: options.method ?? "GET",
    headers: {
      "Content-Type": "application/json",
      "X-API-Key": apiKey,
    },
    body: options.body ? JSON.stringify(options.body) : undefined,
    signal: options.signal,
  });

  if (!response.ok) {
    let detail = `Błąd API (${response.status})`;
    try {
      const data = (await response.json()) as { detail?: string };
      if (data?.detail) {
        detail = data.detail;
      }
    } catch {
      // Keep default detail when body is not JSON.
    }
    throw new ApiError(response.status, detail);
  }

  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export function getMe(signal?: AbortSignal): Promise<UserOut> {
  return apiRequest<UserOut>("/api/v1/admin/me", { signal });
}

export function getCoverageStats(
  scope: CoverageStatsScope = "operational",
  signal?: AbortSignal,
): Promise<CoverageStats> {
  const params = new URLSearchParams({ scope });
  return apiRequest<CoverageStats>(`/api/v1/admin/coverage/stats?${params.toString()}`, { signal });
}

export function getBulkOperations(signal?: AbortSignal): Promise<BulkOperationOut[]> {
  return apiRequest<BulkOperationOut[]>("/api/v1/admin/bulk-operations", { signal });
}

export function listTechnologyTypes(signal?: AbortSignal): Promise<TechnologyTypeOut[]> {
  return apiRequest<TechnologyTypeOut[]>("/api/v1/admin/technology-types", { signal });
}

export function updateTechnologyType(
  typeId: string,
  body: TechnologyTypeUpdateInput,
): Promise<TechnologyTypeOut> {
  return apiRequest<TechnologyTypeOut>(`/api/v1/admin/technology-types/${typeId}`, {
    method: "PUT",
    body,
  });
}

export function listTechnologies(signal?: AbortSignal): Promise<TechnologyOut[]> {
  return apiRequest<TechnologyOut[]>("/api/v1/admin/technologies", { signal });
}

export function createTechnology(body: TechnologyCreateInput): Promise<TechnologyOut> {
  return apiRequest<TechnologyOut>("/api/v1/admin/technologies", {
    method: "POST",
    body,
  });
}

export function updateTechnology(
  techId: string,
  body: TechnologyUpdateInput,
): Promise<TechnologyOut> {
  return apiRequest<TechnologyOut>(`/api/v1/admin/technologies/${techId}`, {
    method: "PUT",
    body,
  });
}

export function deactivateTechnology(techId: string): Promise<void> {
  return apiRequest<void>(`/api/v1/admin/technologies/${techId}`, {
    method: "DELETE",
  });
}

export function listUsers(signal?: AbortSignal): Promise<UserOut[]> {
  return apiRequest<UserOut[]>("/api/v1/admin/users", { signal });
}

export function createUser(body: UserCreateInput): Promise<UserOut> {
  return apiRequest<UserOut>("/api/v1/admin/users", {
    method: "POST",
    body,
  });
}

export function updateUser(userId: string, body: UserUpdateInput): Promise<UserOut> {
  return apiRequest<UserOut>(`/api/v1/admin/users/${userId}`, {
    method: "PUT",
    body,
  });
}

export function deactivateUser(userId: string): Promise<void> {
  return apiRequest<void>(`/api/v1/admin/users/${userId}`, {
    method: "DELETE",
  });
}

export function listUserApiKeys(userId: string, signal?: AbortSignal): Promise<ApiKeyOut[]> {
  return apiRequest<ApiKeyOut[]>(`/api/v1/admin/users/${userId}/api-keys`, { signal });
}

export function createUserApiKey(userId: string, body: ApiKeyCreateInput): Promise<ApiKeyCreated> {
  return apiRequest<ApiKeyCreated>(`/api/v1/admin/users/${userId}/api-keys`, {
    method: "POST",
    body,
  });
}

export function revokeApiKey(keyId: string): Promise<void> {
  return apiRequest<void>(`/api/v1/admin/api-keys/${keyId}`, {
    method: "DELETE",
  });
}

export function listCounties(signal?: AbortSignal): Promise<CountyOut[]> {
  return apiRequest<CountyOut[]>("/api/v1/admin/counties", { signal });
}

export function listMunicipalities(
  countyCode?: number,
  signal?: AbortSignal,
): Promise<MunicipalityOut[]> {
  const suffix = countyCode ? `?county_code=${countyCode}` : "";
  return apiRequest<MunicipalityOut[]>(`/api/v1/admin/municipalities${suffix}`, { signal });
}

export function listLocalities(muniCode?: number, signal?: AbortSignal): Promise<LocalityOut[]> {
  const suffix = muniCode ? `?muni_code=${muniCode}` : "";
  return apiRequest<LocalityOut[]>(`/api/v1/admin/localities${suffix}`, { signal });
}

export function listStreets(localityCode?: number, signal?: AbortSignal): Promise<StreetOut[]> {
  const suffix = localityCode ? `?locality_code=${localityCode}` : "";
  return apiRequest<StreetOut[]>(`/api/v1/admin/streets${suffix}`, { signal });
}

export function searchAddresses(body: AddressSearchRequest): Promise<AddressSearchResult[]> {
  return apiRequest<AddressSearchResult[]>("/api/v1/admin/addresses/search", {
    method: "POST",
    body,
  });
}

export function getAddressDetail(rcCode: number, signal?: AbortSignal): Promise<AddressDetail> {
  return apiRequest<AddressDetail>(`/api/v1/admin/addresses/${rcCode}`, { signal });
}

export function listAddressOfferings(
  rcCode: number,
  signal?: AbortSignal,
): Promise<AddressOfferingOut[]> {
  return apiRequest<AddressOfferingOut[]>(`/api/v1/admin/addresses/${rcCode}/offerings`, {
    signal,
  });
}

export function listAddressZoneCoverage(
  rcCode: number,
  signal?: AbortSignal,
): Promise<ZoneCoverageItem[]> {
  return apiRequest<ZoneCoverageItem[]>(`/api/v1/admin/addresses/${rcCode}/zone-coverage`, {
    signal,
  });
}

export function createAddressOffering(
  rcCode: number,
  body: AddressOfferingCreateInput,
): Promise<AddressOfferingOut> {
  return apiRequest<AddressOfferingOut>(`/api/v1/admin/addresses/${rcCode}/offerings`, {
    method: "POST",
    body,
  });
}

export function updateAddressOffering(
  offeringId: string,
  body: AddressOfferingUpdateInput,
): Promise<AddressOfferingOut> {
  return apiRequest<AddressOfferingOut>(`/api/v1/admin/addresses/offerings/${offeringId}`, {
    method: "PUT",
    body,
  });
}

export function deleteAddressOffering(offeringId: string): Promise<void> {
  return apiRequest<void>(`/api/v1/admin/addresses/offerings/${offeringId}`, {
    method: "DELETE",
  });
}

export function bulkPreview(
  operation: BulkOperationInput,
  rcCodes: number[],
): Promise<BulkPreviewResponse> {
  return apiRequest<BulkPreviewResponse>("/api/v1/admin/bulk/preview", {
    method: "POST",
    body: {
      operation,
      filter: { rc_codes: rcCodes },
    },
  });
}

export function bulkExecute(previewToken: string): Promise<BulkExecuteResponse> {
  return apiRequest<BulkExecuteResponse>("/api/v1/admin/bulk/execute", {
    method: "POST",
    body: { preview_token: previewToken },
  });
}

export function bulkRollback(bulkOperationId: string): Promise<void> {
  return apiRequest<void>(`/api/v1/admin/bulk/${bulkOperationId}/rollback`, {
    method: "POST",
  });
}

export function getMapZonesGeoJson(signal?: AbortSignal): Promise<GeoJsonFeatureCollection> {
  return apiRequest<GeoJsonFeatureCollection>("/api/v1/admin/map/zones/geojson", { signal });
}

export function getMapAddresses(
  bbox: string,
  limit = 3000,
  signal?: AbortSignal,
): Promise<GeoJsonFeatureCollection> {
  return apiRequest<GeoJsonFeatureCollection>(
    `/api/v1/admin/map/addresses?bbox=${encodeURIComponent(bbox)}&limit=${limit}`,
    { signal },
  );
}

export function inPolygon(
  polygonGeojson: Record<string, unknown>,
  limit = 10000,
): Promise<InPolygonResponse> {
  return apiRequest<InPolygonResponse>("/api/v1/admin/map/in-polygon", {
    method: "POST",
    body: {
      polygon_geojson: polygonGeojson,
      limit,
    },
  });
}

export function createZone(body: ZoneCreateInput): Promise<ZoneOut> {
  return apiRequest<ZoneOut>("/api/v1/admin/zones", {
    method: "POST",
    body,
  });
}

export function updateZone(zoneId: string, body: ZoneUpdateInput): Promise<ZoneOut> {
  return apiRequest<ZoneOut>(`/api/v1/admin/zones/${zoneId}`, {
    method: "PUT",
    body,
  });
}

export function getZoneDetail(zoneId: string, signal?: AbortSignal): Promise<ZoneDetail> {
  return apiRequest<ZoneDetail>(`/api/v1/admin/zones/${zoneId}/detail`, { signal });
}

export function createZoneOffering(
  zoneId: string,
  body: ZoneOfferingCreateInput,
): Promise<ZoneOfferingOut> {
  return apiRequest<ZoneOfferingOut>(`/api/v1/admin/zones/${zoneId}/offerings`, {
    method: "POST",
    body,
  });
}

export function updateZoneOffering(
  offeringId: string,
  body: ZoneOfferingUpdateInput,
): Promise<ZoneOfferingOut> {
  return apiRequest<ZoneOfferingOut>(`/api/v1/admin/zones/offerings/${offeringId}`, {
    method: "PUT",
    body,
  });
}

export function deleteZoneOffering(offeringId: string): Promise<void> {
  return apiRequest<void>(`/api/v1/admin/zones/offerings/${offeringId}`, {
    method: "DELETE",
  });
}

export function listZones(signal?: AbortSignal): Promise<ZoneOut[]> {
  return apiRequest<ZoneOut[]>("/api/v1/admin/zones", { signal });
}

export function deleteZone(zoneId: string): Promise<void> {
  return apiRequest<void>(`/api/v1/admin/zones/${zoneId}`, { method: "DELETE" });
}

export function getAuditLog(
  filters: {
    entity_type?: string;
    entity_id?: string;
    user_id?: string;
    since?: string;
    until?: string;
    limit?: number;
    offset?: number;
  },
  signal?: AbortSignal,
): Promise<AuditLogOut[]> {
  const params = new URLSearchParams();
  if (filters.entity_type) {
    params.set("entity_type", filters.entity_type);
  }
  if (filters.entity_id) {
    params.set("entity_id", filters.entity_id);
  }
  if (filters.user_id) {
    params.set("user_id", filters.user_id);
  }
  if (filters.since) {
    params.set("since", filters.since);
  }
  if (filters.until) {
    params.set("until", filters.until);
  }
  params.set("limit", String(filters.limit ?? 50));
  params.set("offset", String(filters.offset ?? 0));

  return apiRequest<AuditLogOut[]>(`/api/v1/admin/audit-log?${params.toString()}`, { signal });
}
