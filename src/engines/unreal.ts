import type { EnginePresentation } from "./index";

export const unrealPresentation: EnginePresentation = {
  name: "Unreal",
  coverClass: "unreal",
  cacheLabel: (source, target) => `UMG · ${source} → ${target}`,
  translationAvailable: true,
};
