"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { bulkRollback, getBulkOperations } from "@/lib/api/client";

export default function OperationsPage(): React.JSX.Element {
  const queryClient = useQueryClient();
  const [onlyActive, setOnlyActive] = useState(false);

  const operationsQuery = useQuery({
    queryKey: ["bulk-operations"],
    queryFn: ({ signal }) => getBulkOperations(signal),
  });

  const rollbackMutation = useMutation({
    mutationFn: (operationId: string) => bulkRollback(operationId),
    onSuccess: () => {
      toast.success("Operacja cofnięta");
      void queryClient.invalidateQueries({ queryKey: ["bulk-operations"] });
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const rows = useMemo(() => {
    const all = operationsQuery.data ?? [];
    if (!onlyActive) {
      return all;
    }
    return all.filter((item) => !item.rolled_back_at);
  }, [onlyActive, operationsQuery.data]);

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold text-zinc-900">Operacje grupowe</h1>

      <Card>
        <CardHeader>
          <CardTitle>Historia bulk operations</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <label className="flex items-center gap-2 text-sm text-zinc-700">
            <input
              type="checkbox"
              checked={onlyActive}
              onChange={(event) => setOnlyActive(event.target.checked)}
            />
            Pokaż tylko aktywne (niecofnięte)
          </label>

          {operationsQuery.isLoading ? <p className="text-sm text-zinc-500">Ładowanie...</p> : null}
          {!operationsQuery.isLoading && rows.length === 0 ? (
            <EmptyState title="Brak operacji do wyświetlenia" />
          ) : null}
          {rows.map((item) => (
            <div
              key={item.id}
              className="grid gap-2 rounded-md border border-zinc-200 p-3 md:grid-cols-6"
            >
              <div className="text-sm font-medium text-zinc-900">{item.operation_type}</div>
              <div className="text-sm text-zinc-700">{item.affected_count} adresów</div>
              <div className="text-sm text-zinc-700">{item.username ?? "unknown"}</div>
              <div className="text-xs text-zinc-600">
                {new Date(item.created_at).toLocaleString()}
              </div>
              <div className="text-xs text-zinc-600">
                {item.rolled_back_at ? "rolled back" : "executed"}
              </div>
              <div>
                {!item.rolled_back_at ? (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => rollbackMutation.mutate(item.id)}
                    disabled={rollbackMutation.isPending}
                  >
                    Cofnij
                  </Button>
                ) : null}
              </div>
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}
