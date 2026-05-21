"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { getMe } from "@/lib/api/client";
import { useAuthStore } from "@/lib/stores/auth";

export function AuthGate({ children }: { children: React.ReactNode }): React.JSX.Element | null {
  const router = useRouter();
  const { apiKey, hydrated, hydrate, setUser, clear } = useAuthStore();

  useEffect(() => {
    hydrate();
  }, [hydrate]);

  const meQuery = useQuery({
    queryKey: ["me"],
    queryFn: ({ signal }) => getMe(signal),
    enabled: hydrated && Boolean(apiKey),
  });

  useEffect(() => {
    if (!hydrated) {
      return;
    }
    if (!apiKey) {
      router.replace("/setup");
      return;
    }
    if (meQuery.isError) {
      clear();
      router.replace("/setup");
      return;
    }
    if (meQuery.data) {
      setUser({
        id: meQuery.data.id,
        username: meQuery.data.username,
        email: meQuery.data.email,
        role: meQuery.data.role,
      });
    }
  }, [apiKey, clear, hydrated, meQuery.data, meQuery.isError, router, setUser]);

  if (!hydrated || (apiKey && meQuery.isLoading)) {
    return (
      <div className="flex min-h-screen items-center justify-center text-sm text-zinc-500">
        Ładowanie...
      </div>
    );
  }

  if (!apiKey) {
    return null;
  }

  return <>{children}</>;
}
