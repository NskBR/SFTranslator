import { renpyPresentation } from "./renpy";
import { unityPresentation } from "./unity";
import { rpgMakerPresentation } from "./rpgmaker";
import { unrealPresentation } from "./unreal";
import type { Game } from "../types";

export interface EnginePresentation {
  name: string;
  coverClass: string;
  cacheLabel: (source: string, target: string) => string;
  translationAvailable?: boolean;
}

const presentations: EnginePresentation[] = [renpyPresentation, unityPresentation, rpgMakerPresentation, unrealPresentation];

export function isTestOnlyGame(game: Pick<Game, "engine" | "runtime" | "executablePath">): boolean {
  return (game.engine === "Unreal" && !/(CatIslandPetrichor|WomanSimulator)/i.test(game.executablePath)) || (game.engine === "RPG Maker" &&
    !["MV", "MZ", "Unite Mono", "Unite IL2CPP"].includes(game.runtime || ""));
}

export function enginePresentation(name: string): EnginePresentation {
  return presentations.find(engine => engine.name === name) ?? {
    name,
    coverClass: "generic",
    cacheLabel: (source, target) => `${source} → ${target}`,
  };
}
