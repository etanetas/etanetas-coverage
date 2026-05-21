"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Input } from "@/components/ui/input";
import { getAuditLog } from "@/lib/api/client";

const PAGE_SIZE = 50;

type Filters = {
  entityType: string;
  entityId: string;
  userId: string;
  since: string;
  until: string;
};

function toIso(value: string): string | undefined {
  if (!value) {
    return undefined;
  }
  return new Date(value).toISOString();
}

export default function AuditPage(): React.JSX.Element {
  const [filters, setFilters] = useState<Filters>({
    entityType: "",
    entityId: "",
    userId: "",
    since: "",
    until: "",
  });
  const [appliedFilters, setAppliedFilters] = useState<Filters>(filters);
  const [page, setPage] = useState(0);

  const auditQuery = useQuery({
    queryKey: ["audit-log", appliedFilters, page],
    queryFn: ({ signal }) =>
      getAuditLog(
        {
          entity_type: appliedFilters.entityType || undefined,
          entity_id: appliedFilters.entityId || undefined,
          user_id: appliedFilters.userId || undefined,
          since: toIso(appliedFilters.since),
          until: toIso(appliedFilters.until),
          limit: PAGE_SIZE,
          offset: page * PAGE_SIZE,
        },
        signal,
      ),
  });

  const items = auditQuery.data ?? [];
  const hasNextPage = items.length === PAGE_SIZE;
  const rangeStart = page * PAGE_SIZE + (items.length > 0 ? 1 : 0);
  const rangeEnd = page * PAGE_SIZE + items.length;

  function applyFilters(): void {
    setPage(0);
    setAppliedFilters(filters);
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold text-zinc-900">Audit log</h1>
      <Card>
        <CardHeader>
          <CardTitle>Filtry</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-2 md:grid-cols-3 xl:grid-cols-5">
          <Input
            placeholder="entity_type"
            value={filters.entityType}
            onChange={(event) =>
              setFilters((prev) => ({ ...prev, entityType: event.target.value }))
            }
          />
          <Input
            placeholder="entity_id"
            value={filters.entityId}
            onChange={(event) => setFilters((prev) => ({ ...prev, entityId: event.target.value }))}
          />
          <Input
            placeholder="user_id (UUID)"
            value={filters.userId}
            onChange={(event) => setFilters((prev) => ({ ...prev, userId: event.target.value }))}
          />
          <Input
            type="datetime-local"
            value={filters.since}
            onChange={(event) => setFilters((prev) => ({ ...prev, since: event.target.value }))}
          />
          <Input
            type="datetime-local"
            value={filters.until}
            onChange={(event) => setFilters((prev) => ({ ...prev, until: event.target.value }))}
          />
          <button
            type="button"
            className="h-10 rounded-md bg-zinc-900 px-4 text-sm font-medium text-white hover:bg-zinc-800"
            onClick={applyFilters}
          >
            Zastosuj
          </button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between gap-4">
          <CardTitle>Historia</CardTitle>
          <div className="flex items-center gap-2">
            <span className="text-xs text-zinc-500">
              {items.length > 0 ? `${rangeStart}–${rangeEnd}` : "Brak wyników"}
            </span>
            <Button
              size="sm"
              variant="outline"
              disabled={page === 0 || auditQuery.isFetching}
              onClick={() => setPage((prev) => Math.max(0, prev - 1))}
            >
              Poprzednia
            </Button>
            <span className="text-xs text-zinc-600">Strona {page + 1}</span>
            <Button
              size="sm"
              variant="outline"
              disabled={!hasNextPage || auditQuery.isFetching}
              onClick={() => setPage((prev) => prev + 1)}
            >
              Następna
            </Button>
          </div>
        </CardHeader>
        <CardContent className="space-y-2">
          {auditQuery.isLoading ? <p className="text-sm text-zinc-500">Ładowanie...</p> : null}
          {auditQuery.isError ? (
            <p className="text-sm text-red-600">Nie udało się pobrać audit log.</p>
          ) : null}
          {!auditQuery.isLoading && !auditQuery.isError && items.length === 0 ? (
            <EmptyState
              title="Brak wpisów audit log"
              description="Zmodyfikuj filtry lub zakres czasu."
            />
          ) : null}
          {items.map((item) => (
            <div key={item.id} className="rounded-md border border-zinc-200 px-3 py-2 text-sm">
              <div className="font-medium text-zinc-900">
                {item.entity_type} · {item.action}
              </div>
              <div className="text-xs text-zinc-600">
                {new Date(item.at).toLocaleString()} · {item.username ?? "system"} · entity_id:{" "}
                {item.entity_id}
              </div>
              {item.diff ? (
                <pre className="mt-1 overflow-auto rounded bg-zinc-50 p-2 text-xs text-zinc-700">
                  {JSON.stringify(item.diff, null, 2)}
                </pre>
              ) : null}
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}
