"use client";

import { LogOut } from "lucide-react";
import { useRouter } from "next/navigation";

import { CommandPalette } from "@/components/layout/command-palette";
import { Button } from "@/components/ui/button";
import { useAuthStore } from "@/lib/stores/auth";

export function Topbar(): React.JSX.Element {
  const router = useRouter();
  const { user, clear } = useAuthStore();

  return (
    <header className="flex h-14 items-center justify-between border-b border-zinc-200 bg-white px-6">
      <div className="text-sm text-zinc-600">
        <span className="font-medium text-zinc-900">Etanetas Coverage</span>
      </div>
      <div className="flex items-center gap-3">
        <CommandPalette />
        {user ? (
          <div className="text-right text-xs leading-tight text-zinc-500">
            <div className="font-medium text-zinc-700">{user.username}</div>
            <div>{user.role}</div>
          </div>
        ) : null}
        <Button
          variant="outline"
          size="sm"
          onClick={() => {
            clear();
            router.replace("/setup");
          }}
        >
          <LogOut className="h-3.5 w-3.5" />
          Wyloguj
        </Button>
      </div>
    </header>
  );
}
