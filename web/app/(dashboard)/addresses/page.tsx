"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Input } from "@/components/ui/input";
import {
  bulkExecute,
  bulkPreview,
  bulkRollback,
  listAddressOfferings,
  listAddressZoneCoverage,
  listCounties,
  listLocalities,
  listMunicipalities,
  listStreets,
  listTechnologies,
  searchAddresses,
} from "@/lib/api/client";
import type {
  AddOfferingOperation,
  AddressSearchRequest,
  ChangeOfferingOperation,
  OfferingStatus,
  RemoveOfferingOperation,
} from "@/lib/api/types";
import { technologyMbpsDefaults } from "@/lib/utils/technology-defaults";

type BulkType = "add_offering" | "change_offering" | "remove_offering";

const today = new Date().toISOString().slice(0, 10);

export default function AddressesPage(): React.JSX.Element {
  const queryClient = useQueryClient();

  const [filters, setFilters] = useState({
    countyCode: "",
    muniCode: "",
    localityCode: "",
    streetCode: "",
    q: "",
    addressType: "",
    onlyWithOffering: false,
    limit: "50",
  });
  const [appliedFilters, setAppliedFilters] = useState<AddressSearchRequest | null>(null);
  const [selectedRc, setSelectedRc] = useState<number[]>([]);
  const [expandedRc, setExpandedRc] = useState<number | null>(null);

  const [bulkType, setBulkType] = useState<BulkType>("add_offering");
  const [bulkTechnologyId, setBulkTechnologyId] = useState("");
  const [bulkStatus, setBulkStatus] = useState<OfferingStatus>("available");
  const [bulkMaxDl, setBulkMaxDl] = useState("1000");
  const [bulkMaxUl, setBulkMaxUl] = useState("500");
  const [bulkStatusSince, setBulkStatusSince] = useState(today);
  const [bulkPlannedUntil, setBulkPlannedUntil] = useState("");
  const [bulkNotes, setBulkNotes] = useState("");
  const [previewToken, setPreviewToken] = useState<string | null>(null);
  const [previewCount, setPreviewCount] = useState<number>(0);
  const [lastBulkOperationId, setLastBulkOperationId] = useState<string | null>(null);

  const countiesQuery = useQuery({
    queryKey: ["counties"],
    queryFn: ({ signal }) => listCounties(signal),
  });
  const municipalitiesQuery = useQuery({
    queryKey: ["municipalities", filters.countyCode],
    queryFn: ({ signal }) =>
      listMunicipalities(filters.countyCode ? Number(filters.countyCode) : undefined, signal),
    enabled: Boolean(filters.countyCode),
  });
  const localitiesQuery = useQuery({
    queryKey: ["localities", filters.muniCode],
    queryFn: ({ signal }) =>
      listLocalities(filters.muniCode ? Number(filters.muniCode) : undefined, signal),
    enabled: Boolean(filters.muniCode),
  });
  const streetsQuery = useQuery({
    queryKey: ["streets", filters.localityCode],
    queryFn: ({ signal }) =>
      listStreets(filters.localityCode ? Number(filters.localityCode) : undefined, signal),
    enabled: Boolean(filters.localityCode),
  });
  const technologiesQuery = useQuery({
    queryKey: ["technologies"],
    queryFn: ({ signal }) => listTechnologies(signal),
  });

  const addressesQuery = useQuery({
    queryKey: ["addresses-search", appliedFilters],
    queryFn: () => searchAddresses(appliedFilters as AddressSearchRequest),
    enabled: Boolean(appliedFilters),
  });

  const previewMutation = useMutation({
    mutationFn: () => bulkPreview(buildBulkOperation(), selectedRc),
    onSuccess: (data) => {
      setPreviewToken(data.preview_token);
      setPreviewCount(data.affected_count);
      toast.success(`Preview gotowy: ${data.affected_count} adresów`);
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
      setExpandedRc(null);
      toast.success(`Wykonano operację na ${result.modified_count} adresach`);
      void queryClient.invalidateQueries({ queryKey: ["addresses-search"] });
      void queryClient.invalidateQueries({ queryKey: ["bulk-operations"] });
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const rollbackMutation = useMutation({
    mutationFn: () => bulkRollback(lastBulkOperationId as string),
    onSuccess: () => {
      toast.success("Cofnięto ostatnią operację");
      setLastBulkOperationId(null);
      void queryClient.invalidateQueries({ queryKey: ["addresses-search"] });
      void queryClient.invalidateQueries({ queryKey: ["bulk-operations"] });
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const techNameById = useMemo(() => {
    const map = new Map<string, string>();
    for (const tech of technologiesQuery.data ?? []) {
      map.set(tech.id, tech.display_name);
    }
    return map;
  }, [technologiesQuery.data]);

  function runSearch(): void {
    if (filters.q.trim().length < 2) {
      toast.error("Podaj minimum 2 znaki w polu wyszukiwania");
      return;
    }
    setSelectedRc([]);
    setPreviewToken(null);
    setPreviewCount(0);
    setAppliedFilters({
      q: filters.q.trim(),
      locality_code: filters.localityCode ? Number(filters.localityCode) : undefined,
      street_code: filters.streetCode ? Number(filters.streetCode) : undefined,
      address_type: filters.addressType
        ? (filters.addressType as "building" | "premises")
        : undefined,
      has_offering: filters.onlyWithOffering,
      limit: Number(filters.limit) || 50,
    });
  }

  function buildBulkOperation():
    | AddOfferingOperation
    | ChangeOfferingOperation
    | RemoveOfferingOperation {
    if (!bulkTechnologyId) {
      throw new Error("Wybierz technologię do operacji bulk");
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

  function toggleSelected(rcCode: number): void {
    setSelectedRc((prev) =>
      prev.includes(rcCode) ? prev.filter((item) => item !== rcCode) : [...prev, rcCode],
    );
  }

  const addressRows = addressesQuery.data ?? [];

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold text-zinc-900">Adresy</h1>

      <Card>
        <CardHeader>
          <CardTitle>Filtry i wyszukiwanie</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="grid gap-2 md:grid-cols-3 xl:grid-cols-4">
            <select
              className="h-10 rounded-md border border-zinc-300 bg-white px-3 text-sm"
              value={filters.countyCode}
              onChange={(event) =>
                setFilters((prev) => ({
                  ...prev,
                  countyCode: event.target.value,
                  muniCode: "",
                  localityCode: "",
                  streetCode: "",
                }))
              }
            >
              <option value="">Apskritis</option>
              {(countiesQuery.data ?? []).map((item) => (
                <option key={item.rc_code} value={item.rc_code}>
                  {item.name}
                </option>
              ))}
            </select>
            <select
              className="h-10 rounded-md border border-zinc-300 bg-white px-3 text-sm"
              value={filters.muniCode}
              onChange={(event) =>
                setFilters((prev) => ({
                  ...prev,
                  muniCode: event.target.value,
                  localityCode: "",
                  streetCode: "",
                }))
              }
              disabled={!filters.countyCode}
            >
              <option value="">Savivaldybė</option>
              {(municipalitiesQuery.data ?? []).map((item) => (
                <option key={item.rc_code} value={item.rc_code}>
                  {item.name}
                </option>
              ))}
            </select>
            <select
              className="h-10 rounded-md border border-zinc-300 bg-white px-3 text-sm"
              value={filters.localityCode}
              onChange={(event) =>
                setFilters((prev) => ({
                  ...prev,
                  localityCode: event.target.value,
                  streetCode: "",
                }))
              }
              disabled={!filters.muniCode}
            >
              <option value="">Gyvenvietė</option>
              {(localitiesQuery.data ?? []).map((item) => (
                <option key={item.rc_code} value={item.rc_code}>
                  {item.name}
                </option>
              ))}
            </select>
            <select
              className="h-10 rounded-md border border-zinc-300 bg-white px-3 text-sm"
              value={filters.streetCode}
              onChange={(event) =>
                setFilters((prev) => ({ ...prev, streetCode: event.target.value }))
              }
              disabled={!filters.localityCode}
            >
              <option value="">Gatvė</option>
              {(streetsQuery.data ?? []).map((item) => (
                <option key={item.rc_code} value={item.rc_code}>
                  {item.full_name}
                </option>
              ))}
            </select>
          </div>

          <div className="grid gap-2 md:grid-cols-[2fr_1fr_1fr_auto]">
            <Input
              placeholder="Szukaj adresu (min. 2 znaki)"
              value={filters.q}
              onChange={(event) => setFilters((prev) => ({ ...prev, q: event.target.value }))}
            />
            <select
              className="h-10 rounded-md border border-zinc-300 bg-white px-3 text-sm"
              value={filters.addressType}
              onChange={(event) =>
                setFilters((prev) => ({ ...prev, addressType: event.target.value }))
              }
            >
              <option value="">Typ adresu</option>
              <option value="building">building</option>
              <option value="premises">premises</option>
            </select>
            <select
              className="h-10 rounded-md border border-zinc-300 bg-white px-3 text-sm"
              value={filters.limit}
              onChange={(event) => setFilters((prev) => ({ ...prev, limit: event.target.value }))}
            >
              <option value="20">20</option>
              <option value="50">50</option>
              <option value="100">100</option>
            </select>
            <Button onClick={runSearch}>Szukaj</Button>
          </div>

          <label className="flex items-center gap-2 text-sm text-zinc-700">
            <input
              type="checkbox"
              checked={filters.onlyWithOffering}
              onChange={(event) =>
                setFilters((prev) => ({ ...prev, onlyWithOffering: event.target.checked }))
              }
            />
            Tylko adresy z ofertą
          </label>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Wyniki</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          {addressesQuery.isFetching ? <p className="text-sm text-zinc-500">Ładowanie...</p> : null}
          {!appliedFilters ? (
            <EmptyState title="Brak wyników" description="Użyj filtrów i kliknij „Szukaj”." />
          ) : null}
          {addressRows.map((row) => (
            <div key={row.rc_code} className="rounded-md border border-zinc-200 px-3 py-2">
              <div className="flex items-start justify-between gap-2">
                <label className="flex items-start gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={selectedRc.includes(row.rc_code)}
                    onChange={() => toggleSelected(row.rc_code)}
                  />
                  <span>
                    <span className="font-medium text-zinc-900">{row.full_address}</span>
                    <span className="ml-2 text-xs text-zinc-500">
                      rc: {row.rc_code} · {row.postal_code ?? "brak kodu"} · {row.address_type}
                    </span>
                  </span>
                </label>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() =>
                    setExpandedRc((prev) => (prev === row.rc_code ? null : row.rc_code))
                  }
                >
                  {expandedRc === row.rc_code ? "Ukryj ofertę" : "Pokaż ofertę"}
                </Button>
              </div>
              {expandedRc === row.rc_code ? (
                <AddressOfferingsInline rcCode={row.rc_code} techNameById={techNameById} />
              ) : null}
            </div>
          ))}
          {appliedFilters && !addressesQuery.isFetching && addressRows.length === 0 ? (
            <EmptyState title="Brak wyników" description="Brak adresów dla podanych filtrów." />
          ) : null}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Bulk operations</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-sm text-zinc-600">Zaznaczono: {selectedRc.length}</p>
          <div className="grid gap-2 md:grid-cols-3">
            <select
              className="h-10 rounded-md border border-zinc-300 bg-white px-3 text-sm"
              value={bulkType}
              onChange={(event) => setBulkType(event.target.value as BulkType)}
            >
              <option value="add_offering">add_offering</option>
              <option value="change_offering">change_offering</option>
              <option value="remove_offering">remove_offering</option>
            </select>
            <select
              className="h-10 rounded-md border border-zinc-300 bg-white px-3 text-sm"
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
              {(technologiesQuery.data ?? []).map((tech) => (
                <option key={tech.id} value={tech.id}>
                  {tech.display_name}
                </option>
              ))}
            </select>
            <select
              className="h-10 rounded-md border border-zinc-300 bg-white px-3 text-sm"
              value={bulkStatus}
              onChange={(event) => setBulkStatus(event.target.value as OfferingStatus)}
              disabled={bulkType === "remove_offering"}
            >
              <option value="available">available</option>
              <option value="planned">planned</option>
              <option value="under_construction">under_construction</option>
              <option value="unavailable">unavailable</option>
            </select>
          </div>
          <div className="grid gap-2 md:grid-cols-4">
            <Input
              type="number"
              placeholder="Max DL"
              value={bulkMaxDl}
              onChange={(event) => setBulkMaxDl(event.target.value)}
              disabled={bulkType === "remove_offering"}
            />
            <Input
              type="number"
              placeholder="Max UL"
              value={bulkMaxUl}
              onChange={(event) => setBulkMaxUl(event.target.value)}
              disabled={bulkType === "remove_offering"}
            />
            <Input
              type="date"
              value={bulkStatusSince}
              onChange={(event) => setBulkStatusSince(event.target.value)}
              disabled={bulkType === "remove_offering"}
            />
            <Input
              type="date"
              value={bulkPlannedUntil}
              onChange={(event) => setBulkPlannedUntil(event.target.value)}
              disabled={bulkType === "remove_offering"}
            />
          </div>
          <Input
            placeholder="Notatka (opcjonalnie)"
            value={bulkNotes}
            onChange={(event) => setBulkNotes(event.target.value)}
            disabled={bulkType === "remove_offering"}
          />
          <div className="flex flex-wrap gap-2">
            <Button
              variant="outline"
              disabled={selectedRc.length === 0 || previewMutation.isPending}
              onClick={() => previewMutation.mutate()}
            >
              Preview
            </Button>
            <Button
              disabled={!previewToken || executeMutation.isPending}
              onClick={() => executeMutation.mutate()}
            >
              Wykonaj
            </Button>
            <Button
              variant="outline"
              disabled={!lastBulkOperationId || rollbackMutation.isPending}
              onClick={() => rollbackMutation.mutate()}
            >
              Cofnij ostatnią operację
            </Button>
          </div>
          {previewToken ? (
            <p className="text-sm text-zinc-700">
              Preview gotowy: {previewCount} rekordów. Kliknij „Wykonaj”, aby zatwierdzić.
            </p>
          ) : null}
        </CardContent>
      </Card>
    </div>
  );
}

function AddressOfferingsInline({
  rcCode,
  techNameById,
}: {
  rcCode: number;
  techNameById: Map<string, string>;
}): React.JSX.Element {
  const offeringsQuery = useQuery({
    queryKey: ["address-offerings", rcCode],
    queryFn: ({ signal }) => listAddressOfferings(rcCode, signal),
  });
  const zoneCoverageQuery = useQuery({
    queryKey: ["address-zone-coverage", rcCode],
    queryFn: ({ signal }) => listAddressZoneCoverage(rcCode, signal),
  });

  if (offeringsQuery.isLoading || zoneCoverageQuery.isLoading) {
    return <p className="mt-2 text-sm text-zinc-500">Ładowanie ofert...</p>;
  }
  if (offeringsQuery.isError || zoneCoverageQuery.isError) {
    return <p className="mt-2 text-sm text-red-600">Nie udało się pobrać ofert.</p>;
  }

  const offerings = offeringsQuery.data ?? [];
  const zoneCoverage = [...(zoneCoverageQuery.data ?? [])].sort(
    (a, b) => b.zone_priority - a.zone_priority,
  );

  const hasAny = offerings.length > 0 || zoneCoverage.some((zone) => zone.offerings.length > 0);
  if (!hasAny) {
    return <p className="mt-2 text-sm text-zinc-500">Brak ofert na tym adresie.</p>;
  }

  return (
    <div className="mt-2 space-y-2 text-xs text-zinc-700">
      {offerings.length > 0 ? (
        <div className="space-y-1">
          <p className="font-medium text-zinc-800">Override adresu</p>
          {offerings.map((offering) => (
            <div key={offering.id}>
              • {techNameById.get(offering.technology_id) ?? offering.technology_id} ·{" "}
              {offering.status} · {offering.max_download_mbps}/{offering.max_upload_mbps} Mbps
            </div>
          ))}
        </div>
      ) : null}

      {zoneCoverage.length > 0 ? (
        <div className="space-y-1">
          <p className="font-medium text-zinc-800">Pokrycie ze strefy</p>
          {zoneCoverage.map((zone) => (
            <div key={zone.zone_id} className="rounded border border-zinc-200 p-2">
              <p className="font-medium text-zinc-900">
                {zone.zone_name} (priorytet {zone.zone_priority})
              </p>
              {zone.offerings.length === 0 ? (
                <p className="text-zinc-500">Strefa bez offeringów.</p>
              ) : (
                zone.offerings.map((offering) => (
                  <div key={offering.id}>
                    • {techNameById.get(offering.technology_id) ?? offering.technology_id} ·{" "}
                    {offering.status} · {offering.max_download_mbps}/{offering.max_upload_mbps} Mbps
                  </div>
                ))
              )}
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}
