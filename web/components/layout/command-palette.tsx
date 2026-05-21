"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { getAddressDetail, searchAddresses } from "@/lib/api/client";

export function CommandPalette(): React.JSX.Element {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const inputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent): void {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setOpen(true);
      }
      if (event.key === "Escape") {
        setOpen(false);
      }
    }

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  useEffect(() => {
    if (!open) {
      return;
    }
    const id = window.setTimeout(() => inputRef.current?.focus(), 50);
    return () => window.clearTimeout(id);
  }, [open]);

  const searchQuery = useQuery({
    queryKey: ["global-command-search", query],
    queryFn: () => searchAddresses({ q: query, limit: 8 }),
    enabled: open && query.trim().length >= 2,
  });

  async function openAddressOnMap(rcCode: number): Promise<void> {
    const detail = await getAddressDetail(rcCode);
    if (detail.lat === null || detail.lon === null) {
      router.push("/map");
      setOpen(false);
      return;
    }
    router.push(`/map?lat=${detail.lat}&lng=${detail.lon}&zoom=18`);
    setOpen(false);
    setQuery("");
  }

  return (
    <>
      <Button size="sm" variant="outline" onClick={() => setOpen(true)}>
        Szukaj
        <span className="ml-1 rounded border border-zinc-300 px-1 py-0.5 text-[10px]">Ctrl+K</span>
      </Button>

      {open ? (
        <div className="fixed inset-0 z-[1000] flex items-start justify-center bg-black/30 p-6 pt-24">
          <div className="w-full max-w-2xl rounded-lg border border-zinc-200 bg-white shadow-xl">
            <div className="border-b border-zinc-200 p-3">
              <Input
                ref={inputRef}
                placeholder="Wyszukaj adres i przejdź na mapę..."
                value={query}
                onChange={(event) => setQuery(event.target.value)}
              />
            </div>
            <div className="max-h-96 overflow-auto p-2">
              {searchQuery.isFetching ? (
                <p className="px-2 py-1 text-xs text-zinc-500">Wyszukiwanie...</p>
              ) : null}
              {(searchQuery.data ?? []).map((item) => (
                <button
                  key={item.rc_code}
                  type="button"
                  className="w-full rounded-md px-2 py-2 text-left text-sm hover:bg-zinc-100"
                  onClick={() => void openAddressOnMap(item.rc_code)}
                >
                  {item.full_address}
                </button>
              ))}
              {!searchQuery.isFetching &&
              query.trim().length >= 2 &&
              (searchQuery.data ?? []).length === 0 ? (
                <p className="px-2 py-1 text-xs text-zinc-500">Brak wyników.</p>
              ) : null}
            </div>
            <div className="flex justify-end border-t border-zinc-200 p-2">
              <Button size="sm" variant="outline" onClick={() => setOpen(false)}>
                Zamknij
              </Button>
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}
