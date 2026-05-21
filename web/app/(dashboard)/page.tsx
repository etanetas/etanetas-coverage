"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { getBulkOperations, getCoverageStats } from "@/lib/api/client";
import type { CoverageStatsScope } from "@/lib/api/types";

export default function DashboardPage(): React.JSX.Element {
  const [scope, setScope] = useState<CoverageStatsScope>("operational");

  const statsQuery = useQuery({
    queryKey: ["coverage-stats", scope],
    queryFn: ({ signal }) => getCoverageStats(scope, signal),
  });
  const operationsQuery = useQuery({
    queryKey: ["bulk-operations"],
    queryFn: ({ signal }) => getBulkOperations(signal),
  });

  if (statsQuery.isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-8 w-48" />
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-24 w-full" />
        </div>
      </div>
    );
  }

  if (statsQuery.isError || !statsQuery.data) {
    return <div className="text-sm text-red-600">Nie udało się pobrać metryk dashboardu.</div>;
  }

  const data = statsQuery.data;
  const coveragePct = data.total_buildings
    ? Math.round((data.covered_buildings / data.total_buildings) * 100)
    : 0;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-zinc-900">Dashboard</h1>
          <p className="mt-1 text-sm text-zinc-600">
            {data.scope_label}
            {data.scope_municipalities.length > 0
              ? `: ${data.scope_municipalities.join(", ")}`
              : ""}
          </p>
        </div>
        <div className="flex rounded-lg border border-zinc-200 bg-white p-1">
          <ScopeButton active={scope === "operational"} onClick={() => setScope("operational")}>
            Region wilenski
          </ScopeButton>
          <ScopeButton active={scope === "all"} onClick={() => setScope("all")}>
            Cała Litwa
          </ScopeButton>
        </div>
      </div>

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <MetricCard label="Adresów (budynki)" value={data.total_buildings.toLocaleString()} />
        <MetricCard
          label="Pokrytych"
          value={`${data.covered_buildings.toLocaleString()} (${coveragePct}%)`}
        />
        <MetricCard
          label="Stref z polygonem"
          value={`${data.zones_with_polygon}/${data.zones_count}`}
          hint="Strefy ISP — globalnie"
        />
        <MetricCard label="Override adresowe" value={data.address_offerings_count.toLocaleString()} />
      </section>

      <section className="grid gap-4 xl:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>
              {scope === "operational" ? "Override adresowe po statusie" : "Pokrycie po statusie"}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {data.addresses_by_status.length === 0 ? (
              <EmptyState title="Brak danych statusów" />
            ) : (
              data.addresses_by_status.map((item) => (
                <div key={item.status} className="flex items-center justify-between text-sm">
                  <span className="capitalize text-zinc-700">
                    {item.status.replaceAll("_", " ")}
                  </span>
                  <span className="font-medium text-zinc-900">{item.count.toLocaleString()}</span>
                </div>
              ))
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Top miejscowości bez pokrycia</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {data.top_uncovered_localities.length === 0 ? (
              <EmptyState title="Brak niepokrytych lokalizacji" />
            ) : (
              data.top_uncovered_localities.slice(0, 8).map((item) => (
                <div key={item.locality_code} className="flex items-center justify-between text-sm">
                  <span className="text-zinc-700">
                    {item.locality_name} ({item.municipality})
                  </span>
                  <span className="font-medium text-zinc-900">
                    {item.uncovered_count.toLocaleString()}
                  </span>
                </div>
              ))
            )}
          </CardContent>
        </Card>
      </section>

      <Card>
        <CardHeader>
          <CardTitle>Ostatnie operacje</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          {operationsQuery.isLoading ? (
            <p className="text-sm text-zinc-500">Ładowanie operacji...</p>
          ) : operationsQuery.isError ? (
            <p className="text-sm text-red-600">Nie udało się pobrać historii operacji.</p>
          ) : operationsQuery.data && operationsQuery.data.length > 0 ? (
            operationsQuery.data.slice(0, 8).map((item) => (
              <div
                key={item.id}
                className="flex items-center justify-between rounded-md border border-zinc-200 px-3 py-2 text-sm"
              >
                <div className="text-zinc-700">
                  <span className="font-medium text-zinc-900">{item.operation_type}</span>
                  {" · "}
                  {item.affected_count} adresów
                  {" · "}
                  {item.username ?? "unknown"}
                </div>
                <div className="text-xs text-zinc-500">
                  {item.rolled_back_at ? "rolled back" : "executed"}
                </div>
              </div>
            ))
          ) : (
            <EmptyState title="Brak operacji" />
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function ScopeButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}): React.JSX.Element {
  return (
    <button
      type="button"
      className={`rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
        active ? "bg-zinc-900 text-white" : "text-zinc-700 hover:bg-zinc-100"
      }`}
      onClick={onClick}
    >
      {children}
    </button>
  );
}

function MetricCard({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint?: string;
}): React.JSX.Element {
  return (
    <Card>
      <CardHeader className="pb-1">
        <p className="text-xs uppercase tracking-wide text-zinc-500">{label}</p>
      </CardHeader>
      <CardContent>
        <p className="text-2xl font-semibold text-zinc-900">{value}</p>
        {hint ? <p className="mt-1 text-xs text-zinc-500">{hint}</p> : null}
      </CardContent>
    </Card>
  );
}
