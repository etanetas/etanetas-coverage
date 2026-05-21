"use client";

import { Button } from "@/components/ui/button";

export default function DashboardError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}): React.JSX.Element {
  return (
    <div className="mx-auto mt-10 max-w-xl rounded-lg border border-red-200 bg-red-50 p-6">
      <h2 className="text-lg font-semibold text-red-900">Wystąpił błąd na stronie</h2>
      <p className="mt-1 text-sm text-red-700">{error.message}</p>
      <div className="mt-4">
        <Button onClick={reset}>Spróbuj ponownie</Button>
      </div>
    </div>
  );
}
