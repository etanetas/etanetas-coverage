import { AuthGate } from "@/components/layout/auth-gate";
import { SidebarNav } from "@/components/layout/sidebar-nav";
import { Topbar } from "@/components/layout/topbar";

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}): React.JSX.Element {
  return (
    <AuthGate>
      <div className="grid min-h-screen grid-cols-[240px_1fr]">
        <aside className="border-r border-zinc-200 bg-white p-4">
          <div className="mb-4 px-3 text-sm font-semibold text-zinc-900">Panel admin</div>
          <SidebarNav />
        </aside>
        <div className="flex min-h-screen flex-col">
          <Topbar />
          <main className="flex-1 p-6">{children}</main>
        </div>
      </div>
    </AuthGate>
  );
}
