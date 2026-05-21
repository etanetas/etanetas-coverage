import type * as React from "react";

import { cn } from "@/lib/utils/cn";

export function Label({
  className,
  ...props
}: React.LabelHTMLAttributes<HTMLLabelElement>): React.JSX.Element {
  return <label className={cn("text-sm font-medium text-zinc-700", className)} {...props} />;
}
