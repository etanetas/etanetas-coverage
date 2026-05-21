"use client";

import {
  Cpu,
  FileText,
  History,
  Layers,
  LayoutDashboard,
  Map as MapIcon,
  Shield,
  Users,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "@/lib/utils/cn";

const items = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/map", label: "Mapa", icon: MapIcon },
  { href: "/addresses", label: "Adresy", icon: FileText },
  { href: "/zones", label: "Strefy", icon: Layers },
  { href: "/technologies", label: "Technologie", icon: Cpu },
  { href: "/users", label: "Użytkownicy", icon: Users },
  { href: "/audit", label: "Audit", icon: Shield },
  { href: "/operations", label: "Operacje", icon: History },
];

export function SidebarNav(): React.JSX.Element {
  const pathname = usePathname();

  return (
    <nav className="flex flex-col gap-1">
      {items.map((item) => {
        const active = pathname === item.href;
        const Icon = item.icon;
        return (
          <Link
            key={item.href}
            href={item.href}
            className={cn(
              "flex items-center gap-2 rounded-md px-3 py-2 text-sm transition-colors",
              active ? "bg-zinc-900 text-white" : "text-zinc-700 hover:bg-zinc-100",
            )}
          >
            <Icon className="h-4 w-4" />
            <span>{item.label}</span>
          </Link>
        );
      })}
    </nav>
  );
}
