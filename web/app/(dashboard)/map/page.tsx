"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BoxSelect, Pentagon, Search, X } from "lucide-react";
import dynamic from "next/dynamic";
import { useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  bulkExecute,
  bulkPreview,
  bulkRollback,
  createAddressOffering,
  createZone,
  createZoneOffering,
  deleteAddressOffering,
  deleteZone,
  deleteZoneOffering,
  getAddressDetail,
  getMapAddresses,
  getMapZonesGeoJson,
  getZoneDetail,
  inPolygon,
  listAddressOfferings,
  listAddressZoneCoverage,
  listTechnologies,
  listTechnologyTypes,
  searchAddresses,
  updateAddressOffering,
  updateZone,
  updateZoneOffering,
} from "@/lib/api/client";
import type {
  AddOfferingOperation,
  AddressOfferingCreateInput,
  AddressOfferingUpdateInput,
  ChangeOfferingOperation,
  OfferingStatus,
  RemoveOfferingOperation,
  ZoneOfferingCreateInput,
  ZoneOfferingUpdateInput,
} from "@/lib/api/types";
import { technologyMbpsDefaults } from "@/lib/utils/technology-defaults";
import type { MapDrawTool } from "@/components/map/map-canvas";

const MapCanvas = dynamic(
  () => import("@/components/map/map-canvas").then((module) => module.MapCanvas),
  { ssr: false },
);

type BulkType = "add_offering" | "change_offering" | "remove_offering";

const today = new Date().toISOString().slice(0, 10);

export default function MapPage(): React.JSX.Element {
  const searchParams = useSearchParams();
  const queryClient = useQueryClient();

  const [bbox, setBbox] = useState<string>("");
  const [zoom, setZoom] = useState<number>(11);
  const [flyTo, setFlyTo] = useState<{ lat: number; lng: number; zoom?: number } | null>(null);
  const [selectedZoneId, setSelectedZoneId] = useState<string | null>(null);
  const [selectedAddressRc, setSelectedAddressRc] = useState<number | null>(null);
  const [selectedAddressLabel, setSelectedAddressLabel] = useState<string>("");
  const [activeInspector, setActiveInspector] = useState<"zone" | "address" | null>(null);
  const [searchOpen, setSearchOpen] = useState(false);
  const [selectedZoneTechFilters, setSelectedZoneTechFilters] = useState<string[]>([]);
  const [drawResetToken, setDrawResetToken] = useState(0);
  const [activeDrawTool, setActiveDrawTool] = useState<MapDrawTool>(null);

  const [searchQ, setSearchQ] = useState("");
  const [zoneName, setZoneName] = useState("");
  const [zoneDescription, setZoneDescription] = useState("");
  const [zonePriority, setZonePriority] = useState("100");
  const [zoneStatus, setZoneStatus] = useState<OfferingStatus>("available");
  const [zoneTechId, setZoneTechId] = useState("");
  const [zoneMaxDl, setZoneMaxDl] = useState("1000");
  const [zoneMaxUl, setZoneMaxUl] = useState("500");
  const [zoneStatusSince, setZoneStatusSince] = useState(today);
  const [zonePlannedUntil, setZonePlannedUntil] = useState("");
  const [zoneNotes, setZoneNotes] = useState("");
  const [drawnPolygon, setDrawnPolygon] = useState<Record<string, unknown> | null>(null);
  const [selectedRc, setSelectedRc] = useState<number[]>([]);
  const [addressTechId, setAddressTechId] = useState("");
  const [addressStatus, setAddressStatus] = useState<OfferingStatus>("available");
  const [addressMaxDl, setAddressMaxDl] = useState("1000");
  const [addressMaxUl, setAddressMaxUl] = useState("500");
  const [addressStatusSince, setAddressStatusSince] = useState(today);
  const [addressPlannedUntil, setAddressPlannedUntil] = useState("");
  const [addressNotes, setAddressNotes] = useState("");

  type OfferingDraft = {
    status: OfferingStatus;
    max_download_mbps: string;
    max_upload_mbps: string;
    status_since: string;
    planned_until: string;
    notes: string;
  };
  const [zoneOfferingDrafts, setZoneOfferingDrafts] = useState<Record<string, OfferingDraft>>({});
  const [addressOfferingDrafts, setAddressOfferingDrafts] = useState<Record<string, OfferingDraft>>(
    {},
  );

  function offeringToDraft(offering: {
    status: OfferingStatus;
    max_download_mbps: number;
    max_upload_mbps: number;
    status_since: string;
    planned_until: string | null;
    notes: string | null;
  }): OfferingDraft {
    return {
      status: offering.status,
      max_download_mbps: String(offering.max_download_mbps),
      max_upload_mbps: String(offering.max_upload_mbps),
      status_since: offering.status_since.slice(0, 10),
      planned_until: offering.planned_until ? offering.planned_until.slice(0, 10) : "",
      notes: offering.notes ?? "",
    };
  }

  function draftToUpdateBody(draft: OfferingDraft): {
    status: OfferingStatus;
    max_download_mbps: number;
    max_upload_mbps: number;
    status_since: string;
    planned_until: string | null;
    notes: string | null;
  } {
    return {
      status: draft.status,
      max_download_mbps: Number(draft.max_download_mbps) || 0,
      max_upload_mbps: Number(draft.max_upload_mbps) || 0,
      status_since: draft.status_since,
      planned_until: draft.planned_until || null,
      notes: draft.notes || null,
    };
  }

  const mapContainerClassName = [
    "map-screen relative h-[calc(100vh-8rem)] overflow-hidden rounded-xl border border-zinc-200 bg-white",
    activeInspector ? "map-has-inspector" : "",
  ]
    .filter(Boolean)
    .join(" ");

  const [bulkType, setBulkType] = useState<BulkType>("add_offering");
  const [bulkTechnologyId, setBulkTechnologyId] = useState("");
  const [bulkStatus, setBulkStatus] = useState<OfferingStatus>("available");
  const [bulkMaxDl, setBulkMaxDl] = useState("1000");
  const [bulkMaxUl, setBulkMaxUl] = useState("500");
  const [bulkStatusSince, setBulkStatusSince] = useState(today);
  const [bulkPlannedUntil, setBulkPlannedUntil] = useState("");
  const [bulkNotes, setBulkNotes] = useState("");
  const [previewToken, setPreviewToken] = useState<string | null>(null);
  const [previewCount, setPreviewCount] = useState(0);
  const [lastBulkOperationId, setLastBulkOperationId] = useState<string | null>(null);

  const zonesQuery = useQuery({
    queryKey: ["map-zones-geojson"],
    queryFn: ({ signal }) => getMapZonesGeoJson(signal),
  });
  const addressesQuery = useQuery({
    queryKey: ["map-addresses", bbox, zoom],
    queryFn: ({ signal }) => getMapAddresses(bbox, 3000, signal),
    enabled: Boolean(bbox) && zoom >= 16,
  });
  const technologiesQuery = useQuery({
    queryKey: ["technologies"],
    queryFn: ({ signal }) => listTechnologies(signal),
  });
  const technologyTypesQuery = useQuery({
    queryKey: ["technology-types"],
    queryFn: ({ signal }) => listTechnologyTypes(signal),
  });
  const zoneDetailQuery = useQuery({
    queryKey: ["zone-detail", selectedZoneId],
    queryFn: ({ signal }) => getZoneDetail(selectedZoneId as string, signal),
    enabled: Boolean(selectedZoneId),
  });
  const addressDetailQuery = useQuery({
    queryKey: ["address-detail", selectedAddressRc],
    queryFn: ({ signal }) => getAddressDetail(selectedAddressRc as number, signal),
    enabled: Boolean(selectedAddressRc),
  });
  const addressOfferingsQuery = useQuery({
    queryKey: ["address-offerings", selectedAddressRc],
    queryFn: ({ signal }) => listAddressOfferings(selectedAddressRc as number, signal),
    enabled: Boolean(selectedAddressRc),
  });
  const addressZoneCoverageQuery = useQuery({
    queryKey: ["address-zone-coverage", selectedAddressRc],
    queryFn: ({ signal }) => listAddressZoneCoverage(selectedAddressRc as number, signal),
    enabled: Boolean(selectedAddressRc),
  });
  const searchQuery = useQuery({
    queryKey: ["map-search", searchQ],
    queryFn: () => searchAddresses({ q: searchQ, limit: 8 }),
    enabled: searchQ.trim().length >= 2,
  });

  const createZoneMutation = useMutation({
    mutationFn: () =>
      createZone({
        name: zoneName,
        description: zoneDescription || null,
        priority: Number(zonePriority) || 100,
        polygon_geojson: drawnPolygon,
      }),
    onSuccess: async (zone) => {
      toast.success("Strefa utworzona");
      setSelectedZoneId(zone.id);
      setActiveInspector("zone");
      setZoneName("");
      setZoneDescription("");
      setZonePriority("100");
      setDrawnPolygon(null);
      setDrawResetToken((prev) => prev + 1);
      if (selectedZoneTechFilters.length > 0) {
        setSelectedZoneTechFilters([]);
        toast.message("Wyczyszczono filtr technologii, aby pokazać nową strefę.");
      }
      await refreshZoneData(zone.id);
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const updateZoneGeometryMutation = useMutation({
    mutationFn: () =>
      updateZone(selectedZoneId as string, {
        polygon_geojson: drawnPolygon,
      }),
    onSuccess: async () => {
      toast.success("Polygon strefy zaktualizowany");
      setDrawnPolygon(null);
      setDrawResetToken((prev) => prev + 1);
      await refreshZoneData(selectedZoneId);
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const updateZoneMetaMutation = useMutation({
    mutationFn: () =>
      updateZone(selectedZoneId as string, {
        name: zoneName || undefined,
        description: zoneDescription || null,
        priority: Number(zonePriority) || 100,
      }),
    onSuccess: async () => {
      toast.success("Dane strefy zaktualizowane");
      await refreshZoneData(selectedZoneId);
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const deleteZoneMutation = useMutation({
    mutationFn: () => deleteZone(selectedZoneId as string),
    onSuccess: async () => {
      toast.success("Strefa usunięta");
      setSelectedZoneId(null);
      setActiveInspector(null);
      await refreshZoneData();
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const createZoneOfferingMutation = useMutation({
    mutationFn: () => {
      if ((zoneDetailQuery.data?.offerings.length ?? 0) > 0) {
        throw new Error("Ta strefa ma już przypisaną technologię");
      }
      return createZoneOffering(selectedZoneId as string, {
        technology_id: zoneTechId,
        status: zoneStatus,
        max_download_mbps: Number(zoneMaxDl),
        max_upload_mbps: Number(zoneMaxUl),
        status_since: zoneStatusSince,
        planned_until: zonePlannedUntil || undefined,
        notes: zoneNotes || undefined,
      } satisfies ZoneOfferingCreateInput);
    },
    onSuccess: async () => {
      toast.success("Dodano offering strefy");
      await refreshZoneData(selectedZoneId);
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const updateZoneOfferingMutation = useMutation({
    mutationFn: ({ offeringId, body }: { offeringId: string; body: ZoneOfferingUpdateInput }) =>
      updateZoneOffering(offeringId, body),
    onSuccess: async (_data, variables) => {
      toast.success("Zaktualizowano offering strefy");
      setZoneOfferingDrafts((prev) => {
        const next = { ...prev };
        delete next[variables.offeringId];
        return next;
      });
      await refreshZoneData(selectedZoneId);
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const deleteZoneOfferingMutation = useMutation({
    mutationFn: (offeringId: string) => deleteZoneOffering(offeringId),
    onSuccess: async (_data, offeringId) => {
      toast.success("Usunięto offering strefy");
      setZoneOfferingDrafts((prev) => {
        const next = { ...prev };
        delete next[offeringId];
        return next;
      });
      await refreshZoneData(selectedZoneId);
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const createAddressOfferingMutation = useMutation({
    mutationFn: () =>
      createAddressOffering(selectedAddressRc as number, {
        technology_id: addressTechId,
        status: addressStatus,
        max_download_mbps: Number(addressMaxDl),
        max_upload_mbps: Number(addressMaxUl),
        status_since: addressStatusSince,
        planned_until: addressPlannedUntil || undefined,
        notes: addressNotes || undefined,
      } satisfies AddressOfferingCreateInput),
    onSuccess: async () => {
      toast.success("Dodano offering adresu");
      await refreshAddressData(selectedAddressRc);
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const updateAddressOfferingMutation = useMutation({
    mutationFn: ({ offeringId, body }: { offeringId: string; body: AddressOfferingUpdateInput }) =>
      updateAddressOffering(offeringId, body),
    onSuccess: async (_data, variables) => {
      toast.success("Zaktualizowano offering adresu");
      setAddressOfferingDrafts((prev) => {
        const next = { ...prev };
        delete next[variables.offeringId];
        return next;
      });
      await refreshAddressData(selectedAddressRc);
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const deleteAddressOfferingMutation = useMutation({
    mutationFn: (offeringId: string) => deleteAddressOffering(offeringId),
    onSuccess: async (_data, offeringId) => {
      toast.success("Usunięto offering adresu");
      setAddressOfferingDrafts((prev) => {
        const next = { ...prev };
        delete next[offeringId];
        return next;
      });
      await refreshAddressData(selectedAddressRc);
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const inPolygonMutation = useMutation({
    mutationFn: (polygon: Record<string, unknown>) => inPolygon(polygon, 10000),
    onSuccess: (result) => {
      setSelectedRc(result.rc_codes);
      toast.success(`Zaznaczono ${result.rc_codes.length} adresów w obszarze`);
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const previewMutation = useMutation({
    mutationFn: () => bulkPreview(buildBulkOperation(), selectedRc),
    onSuccess: (result) => {
      setPreviewToken(result.preview_token);
      setPreviewCount(result.affected_count);
      toast.success(`Preview gotowy: ${result.affected_count} adresów`);
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const executeMutation = useMutation({
    mutationFn: () => bulkExecute(previewToken as string),
    onSuccess: (result) => {
      setLastBulkOperationId(result.bulk_operation_id);
      setPreviewToken(null);
      setPreviewCount(0);
      setSelectedRc([]);
      toast.success(`Wykonano operację na ${result.modified_count} adresach`);
      void queryClient.invalidateQueries({ queryKey: ["map-addresses"] });
      void queryClient.invalidateQueries({ queryKey: ["bulk-operations"] });
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const rollbackMutation = useMutation({
    mutationFn: () => bulkRollback(lastBulkOperationId as string),
    onSuccess: () => {
      setLastBulkOperationId(null);
      toast.success("Cofnięto ostatnią operację");
      void queryClient.invalidateQueries({ queryKey: ["map-addresses"] });
      void queryClient.invalidateQueries({ queryKey: ["bulk-operations"] });
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const searchItems = useMemo(() => searchQuery.data ?? [], [searchQuery.data]);
  const techColorByCode = useMemo(() => {
    const colors = new Map<string, string>();
    for (const item of technologyTypesQuery.data ?? []) {
      colors.set(item.code, item.map_color);
    }
    return colors;
  }, [technologyTypesQuery.data]);
  const availableZoneTechCodes = useMemo(() => {
    const data = zonesQuery.data;
    if (!data) {
      return [] as string[];
    }
    const codes = new Set<string>();
    for (const feature of data.features) {
      const properties = feature.properties as {
        offerings?: Array<{ technology_type?: string }>;
      };
      for (const offering of properties.offerings ?? []) {
        if (offering.technology_type) {
          codes.add(offering.technology_type);
        }
      }
    }
    return [...codes].sort();
  }, [zonesQuery.data]);

  const filteredZones = useMemo(() => {
    const data = zonesQuery.data;
    if (!data) {
      return null;
    }
    if (selectedZoneTechFilters.length === 0) {
      return data;
    }
    return {
      ...data,
      features: data.features.filter((feature) => {
        const properties = feature.properties as {
          offerings?: Array<{ technology_type?: string }>;
        };
        const offeringCodes = (properties.offerings ?? [])
          .map((item) => item.technology_type)
          .filter(Boolean) as string[];
        return offeringCodes.some((code) => selectedZoneTechFilters.includes(code));
      }),
    };
  }, [zonesQuery.data, selectedZoneTechFilters]);

  async function refreshZoneData(zoneId?: string | null): Promise<void> {
    await queryClient.invalidateQueries({ queryKey: ["map-zones-geojson"] });
    await queryClient.refetchQueries({ queryKey: ["map-zones-geojson"], type: "active" });
    if (zoneId) {
      await queryClient.invalidateQueries({ queryKey: ["zone-detail", zoneId] });
      await queryClient.refetchQueries({ queryKey: ["zone-detail", zoneId], type: "active" });
    }
  }

  async function refreshAddressData(addressRc?: number | null): Promise<void> {
    await queryClient.invalidateQueries({ queryKey: ["map-addresses"] });
    await queryClient.refetchQueries({ queryKey: ["map-addresses"], type: "active" });
    if (addressRc) {
      await queryClient.invalidateQueries({ queryKey: ["address-offerings", addressRc] });
      await queryClient.refetchQueries({
        queryKey: ["address-offerings", addressRc],
        type: "active",
      });
      await queryClient.invalidateQueries({ queryKey: ["address-zone-coverage", addressRc] });
      await queryClient.refetchQueries({
        queryKey: ["address-zone-coverage", addressRc],
        type: "active",
      });
    }
  }

  const hasOperationContext =
    selectedRc.length > 0 || Boolean(previewToken) || Boolean(lastBulkOperationId);

  useEffect(() => {
    const zoneId = searchParams.get("zone");
    if (zoneId) {
      setSelectedZoneId(zoneId);
      setSelectedAddressRc(null);
      setActiveInspector("zone");
    }
    const lat = searchParams.get("lat");
    const lng = searchParams.get("lng");
    const zoomParam = searchParams.get("zoom");
    if (lat && lng) {
      const latNum = Number(lat);
      const lngNum = Number(lng);
      const zoomNum = zoomParam ? Number(zoomParam) : undefined;
      if (Number.isFinite(latNum) && Number.isFinite(lngNum)) {
        setFlyTo({
          lat: latNum,
          lng: lngNum,
          zoom: Number.isFinite(zoomNum) ? zoomNum : 17,
        });
      }
    }
  }, [searchParams]);

  useEffect(() => {
    if (!zoneDetailQuery.data) {
      return;
    }
    setZoneName(zoneDetailQuery.data.name ?? "");
    setZoneDescription(zoneDetailQuery.data.description ?? "");
    setZonePriority(String(zoneDetailQuery.data.priority ?? 100));
  }, [zoneDetailQuery.data]);

  function buildBulkOperation():
    | AddOfferingOperation
    | ChangeOfferingOperation
    | RemoveOfferingOperation {
    if (!bulkTechnologyId) {
      throw new Error("Wybierz technologię");
    }
    if (bulkType === "remove_offering") {
      return {
        type: "remove_offering",
        technology_id: bulkTechnologyId,
      };
    }
    if (bulkType === "change_offering") {
      return {
        type: "change_offering",
        technology_id: bulkTechnologyId,
        new_status: bulkStatus,
        new_max_dl_mbps: Number(bulkMaxDl),
        new_max_ul_mbps: Number(bulkMaxUl),
        new_status_since: bulkStatusSince,
        new_planned_until: bulkPlannedUntil || undefined,
        new_notes: bulkNotes || undefined,
      };
    }
    return {
      type: "add_offering",
      technology_id: bulkTechnologyId,
      status: bulkStatus,
      max_dl_mbps: Number(bulkMaxDl),
      max_ul_mbps: Number(bulkMaxUl),
      status_since: bulkStatusSince,
      planned_until: bulkPlannedUntil || undefined,
      notes: bulkNotes || undefined,
    };
  }

  async function focusSearchResult(rcCode: number): Promise<void> {
    try {
      const detail = await getAddressDetail(rcCode);
      if (detail.lat !== null && detail.lon !== null) {
        setFlyTo({ lat: detail.lat, lng: detail.lon, zoom: 18 });
      }
      setSelectedAddressRc(rcCode);
      setSelectedAddressLabel(detail.full_address);
      setSelectedZoneId(null);
      setActiveInspector("address");
      setSearchQ("");
      setSearchOpen(false);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Nie udało się pobrać adresu");
    }
  }

  return (
    <div className={mapContainerClassName}>
      <MapCanvas
        zones={filteredZones}
        addresses={zoom >= 16 ? (addressesQuery.data ?? null) : null}
        flyTo={flyTo}
        selectedZoneId={selectedZoneId}
        activeDrawTool={activeDrawTool}
        onDrawToolChange={setActiveDrawTool}
        showZones={true}
        showAddresses={true}
        drawResetToken={drawResetToken}
        onViewportChange={(nextBbox, nextZoom) => {
          setBbox(nextBbox);
          setZoom(nextZoom);
        }}
        onZoneClick={(zoneId) => {
          setSelectedZoneId(zoneId);
          setSelectedAddressRc(null);
          setActiveInspector("zone");
        }}
        onAddressClick={(rcCode, label) => {
          setSelectedAddressRc(rcCode);
          setSelectedAddressLabel(label);
          setSelectedZoneId(null);
          setActiveInspector("address");
        }}
        onDrawPolygon={(geojson) => {
          setDrawnPolygon(geojson);
          setSelectedRc([]);
          setPreviewToken(null);
          setPreviewCount(0);
          setLastBulkOperationId(null);
          toast.message("Polygon narysowany. Uzupełnij dane strefy i zapisz.");
        }}
        onDrawRectangle={(geojson) => {
          setActiveInspector(null);
          setDrawnPolygon(null);
          setDrawResetToken((prev) => prev + 1);
          inPolygonMutation.mutate(geojson);
          toast.message("Obszar zaznaczony do operacji bulk.");
        }}
        onMapBackgroundClick={() => {
          setSelectedZoneId(null);
          setSelectedAddressRc(null);
          setActiveInspector(null);
          setActiveDrawTool(null);
        }}
      />

      <div className="pointer-events-none absolute inset-0">
        <div className="pointer-events-auto absolute left-3 top-3 z-[450] flex items-center gap-2 rounded-xl border border-zinc-200 bg-white/95 p-2 shadow-sm backdrop-blur">
          <Button
            size="sm"
            variant={searchOpen ? "default" : "outline"}
            onClick={() => setSearchOpen((v) => !v)}
          >
            <Search className="h-4 w-4" />
          </Button>
          {searchOpen ? (
            <div className="relative w-[360px]">
              <Input
                placeholder="Wpisz adres..."
                value={searchQ}
                onChange={(event) => setSearchQ(event.target.value)}
              />
              {searchItems.length > 0 ? (
                <div className="absolute mt-1 max-h-56 w-full overflow-auto rounded-md border border-zinc-200 bg-white p-1 shadow-lg">
                  {searchItems.map((item) => (
                    <button
                      key={item.rc_code}
                      type="button"
                      className="w-full rounded px-2 py-1 text-left text-xs hover:bg-zinc-100"
                      onClick={() => void focusSearchResult(item.rc_code)}
                    >
                      {item.full_address}
                    </button>
                  ))}
                </div>
              ) : null}
            </div>
          ) : null}
          <div className="ml-1 flex max-w-[420px] flex-wrap items-center gap-1">
            {availableZoneTechCodes.length === 0 ? (
              <span className="text-[11px] text-zinc-500">
                Brak technologii do filtrowania stref
              </span>
            ) : (
              availableZoneTechCodes.map((code) => {
                const active = selectedZoneTechFilters.includes(code);
                const techColor = techColorByCode.get(code) ?? "#6b7280";
                return (
                  <button
                    key={code}
                    type="button"
                    className={`rounded-md border px-2 py-1 text-[11px] ${
                      active ? "text-white" : "bg-white text-zinc-700"
                    }`}
                    style={
                      active
                        ? { backgroundColor: techColor, borderColor: techColor }
                        : { borderColor: techColor, color: techColor }
                    }
                    onClick={() =>
                      setSelectedZoneTechFilters((prev) =>
                        prev.includes(code)
                          ? prev.filter((item) => item !== code)
                          : [...prev, code],
                      )
                    }
                  >
                    {code}
                  </button>
                );
              })
            )}
            {selectedZoneTechFilters.length > 0 ? (
              <button
                type="button"
                className="rounded-md border border-zinc-300 bg-white px-2 py-1 text-[11px] text-zinc-700"
                onClick={() => setSelectedZoneTechFilters([])}
              >
                Reset
              </button>
            ) : null}
          </div>
        </div>

        {drawnPolygon ? (
          <div className="pointer-events-auto absolute left-3 top-20 z-[445] w-[300px] rounded-xl border border-zinc-200 bg-white/95 p-3 shadow-sm backdrop-blur">
            <div className="mb-2 flex items-center justify-between">
              <h3 className="text-sm font-semibold text-zinc-900">Nowa/edycja strefy</h3>
              <button
                type="button"
                className="rounded p-1 text-zinc-500 hover:bg-zinc-100"
                onClick={() => {
                  setDrawnPolygon(null);
                  setDrawResetToken((prev) => prev + 1);
                }}
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="space-y-2">
              <Input
                placeholder="Nazwa strefy"
                value={zoneName}
                onChange={(event) => setZoneName(event.target.value)}
              />
              <Input
                placeholder="Opis (opcjonalnie)"
                value={zoneDescription}
                onChange={(event) => setZoneDescription(event.target.value)}
              />
              <Input
                type="number"
                placeholder="Priorytet"
                value={zonePriority}
                onChange={(event) => setZonePriority(event.target.value)}
              />
              <div className="grid grid-cols-2 gap-2">
                <Button
                  size="sm"
                  disabled={!zoneName || createZoneMutation.isPending}
                  onClick={() => createZoneMutation.mutate()}
                >
                  Utwórz
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={!selectedZoneId || updateZoneGeometryMutation.isPending}
                  onClick={() => updateZoneGeometryMutation.mutate()}
                >
                  Zastąp
                </Button>
              </div>
            </div>
          </div>
        ) : null}

        {hasOperationContext ? (
          <div className="pointer-events-auto absolute bottom-20 left-3 top-20 z-[440] w-[280px] overflow-auto rounded-xl border border-zinc-200 bg-white/95 p-3 shadow-sm backdrop-blur">
            <h3 className="mb-2 text-sm font-semibold text-zinc-900">Toolbar operacji</h3>
            <div className="space-y-2">
              <p className="text-xs text-zinc-600">
                Zaznaczonych adresów: <span className="font-semibold">{selectedRc.length}</span>
              </p>
              <select
                className="h-10 w-full rounded-md border border-zinc-300 bg-white px-3 text-sm"
                value={bulkType}
                onChange={(event) => setBulkType(event.target.value as BulkType)}
              >
                <option value="add_offering">add_offering</option>
                <option value="change_offering">change_offering</option>
                <option value="remove_offering">remove_offering</option>
              </select>
              <select
                className="h-10 w-full rounded-md border border-zinc-300 bg-white px-3 text-sm"
                value={bulkTechnologyId}
                onChange={(event) => {
                  const nextId = event.target.value;
                  setBulkTechnologyId(nextId);
                  const { maxDl, maxUl } = technologyMbpsDefaults(technologiesQuery.data, nextId);
                  setBulkMaxDl(maxDl);
                  setBulkMaxUl(maxUl);
                }}
              >
                <option value="">Technologia</option>
                {(technologiesQuery.data ?? []).map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.display_name}
                  </option>
                ))}
              </select>
              <select
                className="h-10 w-full rounded-md border border-zinc-300 bg-white px-3 text-sm"
                value={bulkStatus}
                onChange={(event) => setBulkStatus(event.target.value as OfferingStatus)}
                disabled={bulkType === "remove_offering"}
              >
                <option value="available">available</option>
                <option value="planned">planned</option>
                <option value="under_construction">under_construction</option>
                <option value="unavailable">unavailable</option>
              </select>
              <div className="grid grid-cols-2 gap-2">
                <Input
                  type="number"
                  placeholder="DL"
                  value={bulkMaxDl}
                  disabled={bulkType === "remove_offering"}
                  onChange={(event) => setBulkMaxDl(event.target.value)}
                />
                <Input
                  type="number"
                  placeholder="UL"
                  value={bulkMaxUl}
                  disabled={bulkType === "remove_offering"}
                  onChange={(event) => setBulkMaxUl(event.target.value)}
                />
              </div>
              <Input
                type="date"
                value={bulkStatusSince}
                disabled={bulkType === "remove_offering"}
                onChange={(event) => setBulkStatusSince(event.target.value)}
              />
              <Input
                type="date"
                value={bulkPlannedUntil}
                disabled={bulkType === "remove_offering"}
                onChange={(event) => setBulkPlannedUntil(event.target.value)}
              />
              <Input
                placeholder="Notatka"
                value={bulkNotes}
                disabled={bulkType === "remove_offering"}
                onChange={(event) => setBulkNotes(event.target.value)}
              />
              <div className="grid grid-cols-3 gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  disabled={selectedRc.length === 0 || previewMutation.isPending}
                  onClick={() => previewMutation.mutate()}
                >
                  Preview
                </Button>
                <Button
                  size="sm"
                  disabled={!previewToken || executeMutation.isPending}
                  onClick={() => executeMutation.mutate()}
                >
                  Execute
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={!lastBulkOperationId || rollbackMutation.isPending}
                  onClick={() => rollbackMutation.mutate()}
                >
                  Undo
                </Button>
              </div>
              <Button
                size="sm"
                variant="outline"
                className="w-full"
                onClick={() => {
                  setSelectedRc([]);
                  setDrawnPolygon(null);
                  setPreviewToken(null);
                  setPreviewCount(0);
                  setDrawResetToken((prev) => prev + 1);
                }}
              >
                Wyczyść zaznaczenia
              </Button>
              {previewToken ? (
                <p className="text-xs text-zinc-600">Preview gotowy dla {previewCount} adresów.</p>
              ) : null}
            </div>
          </div>
        ) : null}

        {activeInspector === "zone" && selectedZoneId ? (
          <div className="pointer-events-auto absolute bottom-20 right-3 top-3 z-[440] w-[340px] overflow-auto rounded-xl border border-zinc-200 bg-white/95 p-3 shadow-sm backdrop-blur">
            <div className="mb-2 flex items-center justify-between">
              <h3 className="text-sm font-semibold text-zinc-900">Edycja strefy</h3>
              <button
                type="button"
                className="rounded p-1 text-zinc-500 hover:bg-zinc-100"
                onClick={() => {
                  setActiveInspector(null);
                  setSelectedZoneId(null);
                }}
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            {zoneDetailQuery.isLoading ? (
              <p className="text-sm text-zinc-500">Ładowanie...</p>
            ) : null}
            {zoneDetailQuery.data ? (
              <div className="space-y-3">
                <div className="space-y-2 rounded-md border border-zinc-200 p-3">
                  <Input value={zoneName} onChange={(event) => setZoneName(event.target.value)} />
                  <Input
                    placeholder="Opis (opcjonalnie)"
                    value={zoneDescription}
                    onChange={(event) => setZoneDescription(event.target.value)}
                  />
                  <Input
                    type="number"
                    value={zonePriority}
                    onChange={(event) => setZonePriority(event.target.value)}
                  />
                  <div className="grid grid-cols-2 gap-2">
                    <Button size="sm" onClick={() => updateZoneMetaMutation.mutate()}>
                      Zapisz strefę
                    </Button>
                    <Button size="sm" variant="outline" onClick={() => deleteZoneMutation.mutate()}>
                      Usuń strefę
                    </Button>
                  </div>
                  <p className="text-xs text-zinc-600">
                    Adresów w strefie: {zoneDetailQuery.data.address_count}
                  </p>
                </div>

                {zoneDetailQuery.data.offerings.length === 0 ? (
                  <div className="space-y-2 rounded-md border border-zinc-200 p-3">
                    <p className="text-xs font-medium text-zinc-700">
                      Dodaj offering strefy (1 strefa = 1 technologia)
                    </p>
                    <select
                      className="h-10 w-full rounded-md border border-zinc-300 bg-white px-3 text-sm"
                      value={zoneTechId}
                      onChange={(event) => {
                        const nextId = event.target.value;
                        setZoneTechId(nextId);
                        const { maxDl, maxUl } = technologyMbpsDefaults(
                          technologiesQuery.data,
                          nextId,
                        );
                        setZoneMaxDl(maxDl);
                        setZoneMaxUl(maxUl);
                      }}
                    >
                      <option value="">Technologia</option>
                      {(technologiesQuery.data ?? []).map((item) => (
                        <option key={item.id} value={item.id}>
                          {item.display_name}
                        </option>
                      ))}
                    </select>
                    <select
                      className="h-10 w-full rounded-md border border-zinc-300 bg-white px-3 text-sm"
                      value={zoneStatus}
                      onChange={(event) => setZoneStatus(event.target.value as OfferingStatus)}
                    >
                      <option value="available">available</option>
                      <option value="planned">planned</option>
                      <option value="under_construction">under_construction</option>
                      <option value="unavailable">unavailable</option>
                    </select>
                    <div className="grid grid-cols-2 gap-2">
                      <Input
                        type="number"
                        value={zoneMaxDl}
                        onChange={(event) => setZoneMaxDl(event.target.value)}
                      />
                      <Input
                        type="number"
                        value={zoneMaxUl}
                        onChange={(event) => setZoneMaxUl(event.target.value)}
                      />
                    </div>
                    <Input
                      type="date"
                      value={zoneStatusSince}
                      onChange={(event) => setZoneStatusSince(event.target.value)}
                    />
                    <Input
                      type="date"
                      value={zonePlannedUntil}
                      onChange={(event) => setZonePlannedUntil(event.target.value)}
                    />
                    <Input
                      value={zoneNotes}
                      onChange={(event) => setZoneNotes(event.target.value)}
                      placeholder="Notatka"
                    />
                    <Button
                      size="sm"
                      className="w-full"
                      disabled={!zoneTechId}
                      onClick={() => createZoneOfferingMutation.mutate()}
                    >
                      Dodaj offering
                    </Button>
                  </div>
                ) : (
                  <div className="rounded-md border border-zinc-200 p-3 text-xs text-zinc-600">
                    Ta strefa ma już przypisaną technologię. Edytuj lub usuń istniejący offering
                    poniżej.
                  </div>
                )}

                <div className="space-y-2 rounded-md border border-zinc-200 p-3">
                  <p className="text-xs font-medium text-zinc-700">Edycja offeringu strefy</p>
                  {zoneDetailQuery.data.offerings.length === 0 ? (
                    <p className="text-xs text-zinc-500">Brak offerings.</p>
                  ) : (
                    zoneDetailQuery.data.offerings.map((offering) => {
                      const draft = zoneOfferingDrafts[offering.id] ?? offeringToDraft(offering);
                      const setField = (patch: Partial<OfferingDraft>) => {
                        setZoneOfferingDrafts((prev) => ({
                          ...prev,
                          [offering.id]: { ...draft, ...patch },
                        }));
                      };
                      return (
                        <div
                          key={offering.id}
                          className="space-y-2 rounded border border-zinc-200 p-2 text-xs"
                        >
                          <select
                            className="h-9 w-full rounded-md border border-zinc-300 bg-white px-2 text-xs"
                            value={draft.status}
                            onChange={(event) =>
                              setField({ status: event.target.value as OfferingStatus })
                            }
                          >
                            <option value="available">available</option>
                            <option value="planned">planned</option>
                            <option value="under_construction">under_construction</option>
                            <option value="unavailable">unavailable</option>
                          </select>
                          <div className="grid grid-cols-2 gap-1">
                            <Input
                              type="number"
                              value={draft.max_download_mbps}
                              onChange={(event) =>
                                setField({ max_download_mbps: event.target.value })
                              }
                            />
                            <Input
                              type="number"
                              value={draft.max_upload_mbps}
                              onChange={(event) =>
                                setField({ max_upload_mbps: event.target.value })
                              }
                            />
                          </div>
                          <Input
                            type="date"
                            value={draft.status_since}
                            onChange={(event) => setField({ status_since: event.target.value })}
                          />
                          <Input
                            type="date"
                            value={draft.planned_until}
                            onChange={(event) => setField({ planned_until: event.target.value })}
                          />
                          <Input
                            value={draft.notes}
                            placeholder="Notatka"
                            onChange={(event) => setField({ notes: event.target.value })}
                          />
                          <div className="grid grid-cols-2 gap-1">
                            <Button
                              size="sm"
                              onClick={() =>
                                updateZoneOfferingMutation.mutate({
                                  offeringId: offering.id,
                                  body: draftToUpdateBody(draft),
                                })
                              }
                              disabled={updateZoneOfferingMutation.isPending}
                            >
                              Zapisz
                            </Button>
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() => deleteZoneOfferingMutation.mutate(offering.id)}
                              disabled={deleteZoneOfferingMutation.isPending}
                            >
                              Usuń
                            </Button>
                          </div>
                        </div>
                      );
                    })
                  )}
                </div>
              </div>
            ) : null}
          </div>
        ) : null}

        {activeInspector === "address" && selectedAddressRc ? (
          <div className="pointer-events-auto absolute bottom-20 right-3 top-3 z-[440] w-[340px] overflow-auto rounded-xl border border-zinc-200 bg-white/95 p-3 shadow-sm backdrop-blur">
            <div className="mb-2 flex items-center justify-between">
              <h3 className="text-sm font-semibold text-zinc-900">Edycja adresu</h3>
              <button
                type="button"
                className="rounded p-1 text-zinc-500 hover:bg-zinc-100"
                onClick={() => {
                  setActiveInspector(null);
                  setSelectedAddressRc(null);
                }}
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="space-y-3">
              <div className="space-y-2 rounded-md border border-zinc-200 p-3">
                <p className="text-sm font-medium text-zinc-900">
                  {selectedAddressLabel || `RC ${selectedAddressRc}`}
                </p>
                {addressDetailQuery.data ? (
                  <p className="text-xs text-zinc-600">
                    {addressDetailQuery.data.postal_code ?? "brak kodu"} ·{" "}
                    {addressDetailQuery.data.address_type}
                  </p>
                ) : (
                  <p className="text-xs text-zinc-500">Ładowanie szczegółów...</p>
                )}
                <Button
                  size="sm"
                  variant="outline"
                  className="w-full"
                  onClick={() =>
                    setSelectedRc((prev) =>
                      prev.includes(selectedAddressRc)
                        ? prev.filter((item) => item !== selectedAddressRc)
                        : [...prev, selectedAddressRc],
                    )
                  }
                >
                  {selectedRc.includes(selectedAddressRc) ? "Odznacz z bulk" : "Dodaj do bulk"}
                </Button>
              </div>

              <div className="space-y-2 rounded-md border border-zinc-200 p-3">
                <p className="text-xs font-medium text-zinc-700">Dodaj offering adresu</p>
                <select
                  className="h-10 w-full rounded-md border border-zinc-300 bg-white px-3 text-sm"
                  value={addressTechId}
                  onChange={(event) => {
                    const nextId = event.target.value;
                    setAddressTechId(nextId);
                    const { maxDl, maxUl } = technologyMbpsDefaults(technologiesQuery.data, nextId);
                    setAddressMaxDl(maxDl);
                    setAddressMaxUl(maxUl);
                  }}
                >
                  <option value="">Technologia</option>
                  {(technologiesQuery.data ?? []).map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.display_name}
                    </option>
                  ))}
                </select>
                <select
                  className="h-10 w-full rounded-md border border-zinc-300 bg-white px-3 text-sm"
                  value={addressStatus}
                  onChange={(event) => setAddressStatus(event.target.value as OfferingStatus)}
                >
                  <option value="available">available</option>
                  <option value="planned">planned</option>
                  <option value="under_construction">under_construction</option>
                  <option value="unavailable">unavailable</option>
                </select>
                <div className="grid grid-cols-2 gap-2">
                  <Input
                    type="number"
                    value={addressMaxDl}
                    onChange={(event) => setAddressMaxDl(event.target.value)}
                  />
                  <Input
                    type="number"
                    value={addressMaxUl}
                    onChange={(event) => setAddressMaxUl(event.target.value)}
                  />
                </div>
                <Input
                  type="date"
                  value={addressStatusSince}
                  onChange={(event) => setAddressStatusSince(event.target.value)}
                />
                <Input
                  type="date"
                  value={addressPlannedUntil}
                  onChange={(event) => setAddressPlannedUntil(event.target.value)}
                />
                <Input
                  value={addressNotes}
                  onChange={(event) => setAddressNotes(event.target.value)}
                  placeholder="Notatka"
                />
                <Button
                  size="sm"
                  className="w-full"
                  disabled={!addressTechId}
                  onClick={() => createAddressOfferingMutation.mutate()}
                >
                  Dodaj offering
                </Button>
              </div>

              <div className="space-y-2 rounded-md border border-zinc-200 p-3">
                <p className="text-xs font-medium text-zinc-700">Pokrycie ze strefy</p>
                {addressZoneCoverageQuery.isLoading ? (
                  <p className="text-xs text-zinc-500">Ładowanie...</p>
                ) : (addressZoneCoverageQuery.data ?? []).length === 0 ? (
                  <p className="text-xs text-zinc-500">Adres nie leży w żadnej strefie.</p>
                ) : (
                  [...(addressZoneCoverageQuery.data ?? [])]
                    .sort((a, b) => b.zone_priority - a.zone_priority)
                    .map((zone) => (
                      <div
                        key={zone.zone_id}
                        className="space-y-1 rounded border border-zinc-200 p-2 text-xs"
                      >
                        <button
                          type="button"
                          className="block text-left text-xs font-medium text-zinc-900 hover:underline"
                          onClick={() => {
                            setSelectedZoneId(zone.zone_id);
                            setSelectedAddressRc(null);
                            setActiveInspector("zone");
                          }}
                        >
                          {zone.zone_name} (priorytet {zone.zone_priority})
                        </button>
                        {zone.offerings.length === 0 ? (
                          <p className="text-zinc-500">Strefa bez offeringów.</p>
                        ) : (
                          zone.offerings.map((offering) => (
                            <div key={offering.id} className="text-zinc-700">
                              • {offering.status} · {offering.max_download_mbps}/
                              {offering.max_upload_mbps} Mbps
                            </div>
                          ))
                        )}
                      </div>
                    ))
                )}
              </div>

              <div className="space-y-2 rounded-md border border-zinc-200 p-3">
                <p className="text-xs font-medium text-zinc-700">
                  Edycja offerings adresu (override)
                </p>
                {(addressOfferingsQuery.data ?? []).length === 0 ? (
                  <p className="text-xs text-zinc-500">Brak override-ów.</p>
                ) : (
                  (addressOfferingsQuery.data ?? []).map((offering) => {
                    const draft = addressOfferingDrafts[offering.id] ?? offeringToDraft(offering);
                    const setField = (patch: Partial<OfferingDraft>) => {
                      setAddressOfferingDrafts((prev) => ({
                        ...prev,
                        [offering.id]: { ...draft, ...patch },
                      }));
                    };
                    return (
                      <div
                        key={offering.id}
                        className="space-y-2 rounded border border-zinc-200 p-2 text-xs"
                      >
                        <select
                          className="h-9 w-full rounded-md border border-zinc-300 bg-white px-2 text-xs"
                          value={draft.status}
                          onChange={(event) =>
                            setField({ status: event.target.value as OfferingStatus })
                          }
                        >
                          <option value="available">available</option>
                          <option value="planned">planned</option>
                          <option value="under_construction">under_construction</option>
                          <option value="unavailable">unavailable</option>
                        </select>
                        <div className="grid grid-cols-2 gap-1">
                          <Input
                            type="number"
                            value={draft.max_download_mbps}
                            onChange={(event) =>
                              setField({ max_download_mbps: event.target.value })
                            }
                          />
                          <Input
                            type="number"
                            value={draft.max_upload_mbps}
                            onChange={(event) => setField({ max_upload_mbps: event.target.value })}
                          />
                        </div>
                        <Input
                          type="date"
                          value={draft.status_since}
                          onChange={(event) => setField({ status_since: event.target.value })}
                        />
                        <Input
                          type="date"
                          value={draft.planned_until}
                          onChange={(event) => setField({ planned_until: event.target.value })}
                        />
                        <Input
                          value={draft.notes}
                          placeholder="Notatka"
                          onChange={(event) => setField({ notes: event.target.value })}
                        />
                        <div className="grid grid-cols-2 gap-1">
                          <Button
                            size="sm"
                            onClick={() =>
                              updateAddressOfferingMutation.mutate({
                                offeringId: offering.id,
                                body: draftToUpdateBody(draft),
                              })
                            }
                            disabled={updateAddressOfferingMutation.isPending}
                          >
                            Zapisz
                          </Button>
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => deleteAddressOfferingMutation.mutate(offering.id)}
                            disabled={deleteAddressOfferingMutation.isPending}
                          >
                            Usuń
                          </Button>
                        </div>
                      </div>
                    );
                  })
                )}
              </div>
            </div>
          </div>
        ) : null}

        <div className="pointer-events-auto absolute bottom-4 left-1/2 z-[450] flex -translate-x-1/2 items-center gap-1 rounded-xl border border-zinc-200 bg-white/95 p-1.5 shadow-sm backdrop-blur">
          <Button
            size="sm"
            variant={activeDrawTool === "polygon" ? "default" : "outline"}
            title="Rysuj strefę (polygon)"
            aria-label="Rysuj strefę"
            onClick={() =>
              setActiveDrawTool((prev) => (prev === "polygon" ? null : "polygon"))
            }
          >
            <Pentagon className="h-4 w-4" />
            <span className="hidden sm:inline">Strefa</span>
          </Button>
          <Button
            size="sm"
            variant={activeDrawTool === "rectangle" ? "default" : "outline"}
            title="Zaznacz obszar adresów (bulk)"
            aria-label="Zaznacz obszar"
            onClick={() =>
              setActiveDrawTool((prev) => (prev === "rectangle" ? null : "rectangle"))
            }
          >
            <BoxSelect className="h-4 w-4" />
            <span className="hidden sm:inline">Zaznacz</span>
          </Button>
        </div>
      </div>
    </div>
  );
}
