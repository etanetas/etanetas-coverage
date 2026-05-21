import type { TechnologyOut } from "@/lib/api/types";

const FALLBACK_MAX_DL = 1000;
const FALLBACK_MAX_UL = 500;

export function technologyMbpsDefaults(
  technologies: TechnologyOut[] | undefined,
  technologyId: string,
): { maxDl: string; maxUl: string } {
  const tech = technologies?.find((item) => item.id === technologyId);
  if (!tech) {
    return {
      maxDl: String(FALLBACK_MAX_DL),
      maxUl: String(FALLBACK_MAX_UL),
    };
  }

  return {
    maxDl: String(tech.theoretical_max_dl_mbps ?? FALLBACK_MAX_DL),
    maxUl: String(tech.theoretical_max_ul_mbps ?? FALLBACK_MAX_UL),
  };
}
