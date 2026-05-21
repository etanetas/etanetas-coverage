"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  createTechnology,
  deactivateTechnology,
  listTechnologies,
  listTechnologyTypes,
  updateTechnology,
  updateTechnologyType,
} from "@/lib/api/client";
import type { TechnologyCreateInput, TechnologyOut, TechnologyTypeOut } from "@/lib/api/types";

type EditableType = Pick<
  TechnologyTypeOut,
  "display_name" | "public_name" | "sort_order" | "active" | "map_color"
>;
type EditableTech = Pick<
  TechnologyOut,
  "display_name" | "theoretical_max_dl_mbps" | "theoretical_max_ul_mbps" | "sort_order" | "active"
>;

function toNumberOrNull(value: string): number | null {
  if (!value.trim()) {
    return null;
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

export default function TechnologiesPage(): React.JSX.Element {
  const queryClient = useQueryClient();
  const [typeDrafts, setTypeDrafts] = useState<Record<string, EditableType>>({});
  const [techDrafts, setTechDrafts] = useState<Record<string, EditableTech>>({});
  const [newTech, setNewTech] = useState<TechnologyCreateInput>({
    type_id: "",
    variant_code: "",
    display_name: "",
    theoretical_max_dl_mbps: null,
    theoretical_max_ul_mbps: null,
    sort_order: 100,
    active: true,
  });

  const typesQuery = useQuery({
    queryKey: ["technology-types"],
    queryFn: ({ signal }) => listTechnologyTypes(signal),
  });
  const techQuery = useQuery({
    queryKey: ["technologies"],
    queryFn: ({ signal }) => listTechnologies(signal),
  });

  const saveTypeMutation = useMutation({
    mutationFn: ({ id, body }: { id: string; body: EditableType }) =>
      updateTechnologyType(id, body),
    onSuccess: () => {
      toast.success("Zapisano typ technologii");
      void queryClient.invalidateQueries({ queryKey: ["technology-types"] });
      void queryClient.invalidateQueries({ queryKey: ["map-zones-geojson"] });
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const createTechMutation = useMutation({
    mutationFn: (body: TechnologyCreateInput) => createTechnology(body),
    onSuccess: () => {
      toast.success("Dodano technologię");
      setNewTech({
        type_id: "",
        variant_code: "",
        display_name: "",
        theoretical_max_dl_mbps: null,
        theoretical_max_ul_mbps: null,
        sort_order: 100,
        active: true,
      });
      void queryClient.invalidateQueries({ queryKey: ["technologies"] });
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const saveTechMutation = useMutation({
    mutationFn: ({ id, body }: { id: string; body: EditableTech }) => updateTechnology(id, body),
    onSuccess: () => {
      toast.success("Zapisano technologię");
      void queryClient.invalidateQueries({ queryKey: ["technologies"] });
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const deactivateTechMutation = useMutation({
    mutationFn: (id: string) => deactivateTechnology(id),
    onSuccess: () => {
      toast.success("Technologia zdezaktywowana");
      void queryClient.invalidateQueries({ queryKey: ["technologies"] });
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const typeRows = useMemo(() => typesQuery.data ?? [], [typesQuery.data]);
  const techRows = useMemo(() => techQuery.data ?? [], [techQuery.data]);

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold text-zinc-900">Technologie</h1>

      <Card>
        <CardHeader>
          <CardTitle>Typy technologii</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {typesQuery.isLoading ? <p className="text-sm text-zinc-500">Ładowanie...</p> : null}
          {typeRows.map((item) => {
            const draft = typeDrafts[item.id] ?? {
              display_name: item.display_name,
              public_name: item.public_name,
              sort_order: item.sort_order,
              active: item.active,
              map_color: item.map_color,
            };
            return (
              <div
                key={item.id}
                className="grid gap-2 rounded-md border border-zinc-200 p-3 lg:grid-cols-7"
              >
                <Input disabled value={item.code} />
                <Input
                  value={draft.display_name}
                  onChange={(event) => {
                    setTypeDrafts((prev) => ({
                      ...prev,
                      [item.id]: { ...draft, display_name: event.target.value },
                    }));
                  }}
                />
                <Input
                  value={draft.public_name}
                  onChange={(event) => {
                    setTypeDrafts((prev) => ({
                      ...prev,
                      [item.id]: { ...draft, public_name: event.target.value },
                    }));
                  }}
                />
                <Input
                  type="number"
                  value={draft.sort_order}
                  onChange={(event) => {
                    setTypeDrafts((prev) => ({
                      ...prev,
                      [item.id]: { ...draft, sort_order: Number(event.target.value) || 0 },
                    }));
                  }}
                />
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="color"
                    value={draft.map_color}
                    title="Kolor na mapie"
                    className="h-10 w-12 cursor-pointer rounded border border-zinc-300 bg-white p-1"
                    onChange={(event) => {
                      setTypeDrafts((prev) => ({
                        ...prev,
                        [item.id]: { ...draft, map_color: event.target.value },
                      }));
                    }}
                  />
                  <span className="font-mono text-xs text-zinc-600">{draft.map_color}</span>
                </label>
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={draft.active}
                    onChange={(event) => {
                      setTypeDrafts((prev) => ({
                        ...prev,
                        [item.id]: { ...draft, active: event.target.checked },
                      }));
                    }}
                  />
                  Aktywny
                </label>
                <Button
                  size="sm"
                  onClick={() => saveTypeMutation.mutate({ id: item.id, body: draft })}
                  disabled={saveTypeMutation.isPending}
                >
                  Zapisz
                </Button>
              </div>
            );
          })}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Dodaj wariant technologii</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-2 md:grid-cols-3">
          <select
            className="h-10 rounded-md border border-zinc-300 bg-white px-3 text-sm"
            value={newTech.type_id}
            onChange={(event) => setNewTech((prev) => ({ ...prev, type_id: event.target.value }))}
          >
            <option value="">Wybierz typ</option>
            {typeRows.map((item) => (
              <option key={item.id} value={item.id}>
                {item.display_name} ({item.code})
              </option>
            ))}
          </select>
          <Input
            placeholder="variant_code"
            value={newTech.variant_code}
            onChange={(event) =>
              setNewTech((prev) => ({ ...prev, variant_code: event.target.value }))
            }
          />
          <Input
            placeholder="display_name"
            value={newTech.display_name}
            onChange={(event) =>
              setNewTech((prev) => ({ ...prev, display_name: event.target.value }))
            }
          />
          <Input
            type="number"
            placeholder="Max DL"
            value={newTech.theoretical_max_dl_mbps ?? ""}
            onChange={(event) =>
              setNewTech((prev) => ({
                ...prev,
                theoretical_max_dl_mbps: toNumberOrNull(event.target.value),
              }))
            }
          />
          <Input
            type="number"
            placeholder="Max UL"
            value={newTech.theoretical_max_ul_mbps ?? ""}
            onChange={(event) =>
              setNewTech((prev) => ({
                ...prev,
                theoretical_max_ul_mbps: toNumberOrNull(event.target.value),
              }))
            }
          />
          <div className="flex items-center gap-2">
            <Button
              onClick={() => createTechMutation.mutate(newTech)}
              disabled={!newTech.type_id || !newTech.variant_code || !newTech.display_name}
            >
              Dodaj
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Warianty technologii</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {techQuery.isLoading ? <p className="text-sm text-zinc-500">Ładowanie...</p> : null}
          {techRows.map((item) => {
            const draft = techDrafts[item.id] ?? {
              display_name: item.display_name,
              theoretical_max_dl_mbps: item.theoretical_max_dl_mbps,
              theoretical_max_ul_mbps: item.theoretical_max_ul_mbps,
              sort_order: item.sort_order,
              active: item.active,
            };

            return (
              <div
                key={item.id}
                className="grid gap-2 rounded-md border border-zinc-200 p-3 lg:grid-cols-7"
              >
                <Input disabled value={item.variant_code} />
                <Input
                  value={draft.display_name}
                  onChange={(event) => {
                    setTechDrafts((prev) => ({
                      ...prev,
                      [item.id]: { ...draft, display_name: event.target.value },
                    }));
                  }}
                />
                <Input
                  type="number"
                  value={draft.theoretical_max_dl_mbps ?? ""}
                  onChange={(event) => {
                    setTechDrafts((prev) => ({
                      ...prev,
                      [item.id]: {
                        ...draft,
                        theoretical_max_dl_mbps: toNumberOrNull(event.target.value),
                      },
                    }));
                  }}
                />
                <Input
                  type="number"
                  value={draft.theoretical_max_ul_mbps ?? ""}
                  onChange={(event) => {
                    setTechDrafts((prev) => ({
                      ...prev,
                      [item.id]: {
                        ...draft,
                        theoretical_max_ul_mbps: toNumberOrNull(event.target.value),
                      },
                    }));
                  }}
                />
                <Input
                  type="number"
                  value={draft.sort_order}
                  onChange={(event) => {
                    setTechDrafts((prev) => ({
                      ...prev,
                      [item.id]: { ...draft, sort_order: Number(event.target.value) || 0 },
                    }));
                  }}
                />
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={draft.active}
                    onChange={(event) =>
                      setTechDrafts((prev) => ({
                        ...prev,
                        [item.id]: { ...draft, active: event.target.checked },
                      }))
                    }
                  />
                  Aktywny
                </label>
                <div className="flex gap-2">
                  <Button
                    size="sm"
                    onClick={() => saveTechMutation.mutate({ id: item.id, body: draft })}
                    disabled={saveTechMutation.isPending}
                  >
                    Zapisz
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => deactivateTechMutation.mutate(item.id)}
                    disabled={deactivateTechMutation.isPending}
                  >
                    Dezaktywuj
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
