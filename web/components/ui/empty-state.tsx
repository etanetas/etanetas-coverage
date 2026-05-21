import { cn } from "@/lib/utils/cn";

export function EmptyState({
  title,
  description,
  className,
}: {
  title: string;
  description?: string;
  className?: string;
}): React.JSX.Element {
  return (
    <div
      className={cn(
        "rounded-md border border-dashed border-zinc-300 bg-white p-6 text-center",
        className,
      )}
    >
      <p className="text-sm font-medium text-zinc-800">{title}</p>
      {description ? <p className="mt-1 text-xs text-zinc-500">{description}</p> : null}
    </div>
  );
}
