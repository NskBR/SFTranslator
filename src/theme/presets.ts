import type { AppSettings, ThemePreferences } from "../types";

export const defaultAppearance: ThemePreferences = {
  accent: null, background: null, panel: null, surface: null,
  font: "system", gradient: "none", gradientAngle: 135,
  animations: true, animatedIcons: true, iconStyle: "default", imageId: null,
  localThemeId: null, officialThemeId: null, localThemeVariant: 0, customCss: "",
};

export const initialSettings: AppSettings = {
  enableExperimentalChainedFlow: false, theme: "amber", appearance: defaultAppearance,
};

export const themePresets: { id: AppSettings["theme"]; name: string; background: string; panel: string; surface: string; accent: string; gradient?: string }[] = [
  { id: "amber", name: "Padrão", background: "#161a1e", panel: "#1d2228", surface: "#252b33", accent: "#3b82f6" },
  { id: "ocean", name: "Azul neon", background: "#0b1638", panel: "#142349", surface: "#1c315c", accent: "#3b82f6", gradient: "linear-gradient(135deg,#0b1638,#040714)" },
  { id: "violet", name: "Roxo gradiente", background: "#320938", panel: "#2c173e", surface: "#3d2553", accent: "#8b5cf6", gradient: "linear-gradient(135deg,#320938,#050a1e)" },
  { id: "contrast", name: "Alto contraste", background: "#0a0c10", panel: "#11151c", surface: "#1b202a", accent: "#eab308", gradient: "linear-gradient(135deg,#0a0c10,#040507)" },
  { id: "crimson", name: "Carmim Obscuro", background: "#41010d", panel: "#261017", surface: "#3a1722", accent: "#ef4444", gradient: "linear-gradient(135deg,#41010d,#080204)" },
  { id: "forest", name: "Crepúsculo Esmeralda", background: "#0a2818", panel: "#142b1e", surface: "#1d3928", accent: "#10b981", gradient: "linear-gradient(135deg,#0a2818,#040d08)" },
];

export type LocalTheme = {
  id: string; name: string; author: string; variants: {
    name: string; image: string; preview: string; medium?: string; compact?: string;
    preset: string; appearance: { palette?: { surface: string; raised: string; accent: string; strong: string }; geometry?: { window?: string; cardRadius?: string; navigationRadius?: string }; font?: string };
    darkness: number; panelOpacity: number; position: "center" | "left" | "right";
  }[];
};

export type ThemeImage = { id: string; name: string; mime: string };
