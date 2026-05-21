"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Input } from "@/components/ui/input";
import { deleteZone, listZones, updateZone } from "@/lib/api/client";

type ZoneDraft = {
  name: string;
  priority: number;
};

export default function ZonesPage(): React.JSX.Element {
  const queryClient = useQueryClient();
  const [drafts, setDrafts] = useState<Record<string, ZoneDraft>>({});

  const zonesQuery = useQuery({
    queryKey: ["zones-list"],
    queryFn: ({ signal }) => listZones(signal),
  });

  const updateMutation = useMutation({
    mutationFn: ({ zoneId, body }: { zoneId: string; body: ZoneDraft }) => updateZone(zoneId, body),
    onSuccess: () => {
      toast.success("Strefa zaktualizowana");
      void queryClient.invalidateQueries({ queryKey: ["zones-list"] });
      void queryClient.invalidateQueries({ queryKey: ["map-zones-geojson"] });
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const deleteMutation = useMutation({
    mutationFn: (zoneId: string) => deleteZone(zoneId),
    onSuccess: () => {
      toast.success("Strefa usunięta");
      void queryClient.invalidateQueries({ queryKey: ["zones-list"] });
      void queryClient.invalidateQueries({ queryKey: ["map-zones-geojson"] });
    },
    onError: (error: Error) => toast.error(error.message),
  });

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold text-zinc-900">Strefy pokrycia</h1>
      <Card>
        <CardHeader>
          <CardTitle>Lista stref</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {zonesQuery.isLoading ? <p className="text-sm text-zinc-500">Ładowanie...</p> : null}
          {!zonesQuery.isLoading && (zonesQuery.data ?? []).length === 0 ? (
            <EmptyState title="Brak stref" description="Dodaj strefę na ekranie mapy." />
          ) : null}
          {(zonesQuery.data ?? []).map((zone) => {
            const draft = drafts[zone.id] ?? { name: zone.name, priority: zone.priority };
            return (
              <div
                key={zone.id}
                className="grid gap-2 rounded-md border border-zinc-200 p-3 lg:grid-cols-6"
              >
                <Input
                  value={draft.name}
                  onChange={(event) =>
                    setDrafts((prev) => ({
                      ...prev,
                      [zone.id]: { ...draft, name: event.target.value },
                    }))
                  }
                />
                <Input
                  type="number"
                  value={draft.priority}
                  onChange={(event) =>
                    setDrafts((prev) => ({
                      ...prev,
                      [zone.id]: { ...draft, priority: Number(event.target.value) || 0 },
                    }))
                  }
                />
                <div className="flex items-center text-xs text-zinc-600">
                  {zone.has_polygon ? "polygon: yes" : "polygon: no"}
                </div>
                <div className="flex items-center text-xs text-zinc-600">
                  {zone.created_at ? new Date(zone.created_at).toLocaleString() : ""}
                </div>
                <Link
                  href={`/map?zone=${zone.id}`}
                  className="inline-flex h-10 items-center justify-center rounded-md border border-zinc-300 px-3 text-sm hover:bg-zinc-50"
                >
                  Otwórz na mapie
                </Link>
                <div className="flex gap-2">
                  <Button
                    size="sm"
                    onClick={() => updateMutation.mutate({ zoneId: zone.id, body: draft })}
                    disabled={updateMutation.isPending}
                  >
                    Zapisz
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => deleteMutation.mutate(zone.id)}
                    disabled={deleteMutation.isPending}
                  >
                    Usuń
                  </Button>
                </div>
              </div>
            );
          })}
        </CardContent>
      </Card>
    </div>
  );
}
