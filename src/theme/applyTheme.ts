import { invoke } from "@tauri-apps/api/core";
import type { AppSettings } from "../types";
import { defaultAppearance, themePresets, type LocalTheme } from "./presets";
import { compileCustomCss } from "./customCss";
import { officialGroupFor, officialPalette } from "./officialCatalog";

const hex = (value: unknown): value is string => typeof value === "string" && /^#[0-9a-f]{6}$/i.test(value);
const hash = (value: unknown): value is string => typeof value === "string" && /^[0-9a-f]{64}$/.test(value);
const gradients: Record<string, [string, string]> = {
  aurora: ["#0d3840", "#563277"], sunset: ["#642c51", "#9d572f"],
  ocean: ["#074c72", "#10334c"], cyberpunk: ["#672276", "#123c68"],
};
let latestRequest = 0;
let cachedImage: { id: string; data: string } | null = null;

function rgba(color: string, opacity: number) {
  const parts = color.slice(1).match(/../g)!.map(part => parseInt(part, 16));
  return `rgba(${parts.join(",")},${opacity})`;
}

/** Apply only validated visual tokens. Functional status colors stay outside theme control. */
export async function applyTheme(settings: AppSettings): Promise<void> {
  const request = ++latestRequest;
  const root = document.documentElement;
  const appearance = { ...defaultAppearance, ...settings.appearance };
  const baseTheme = themePresets.find(item => item.id === settings.theme) || themePresets[0];
  root.dataset.theme = settings.theme;
  root.dataset.animations = appearance.animations ? "on" : "off";
  root.dataset.animatedIcons = appearance.animatedIcons ? "on" : "off";
  root.dataset.iconStyle = appearance.iconStyle;
  root.dataset.gradient = appearance.gradient === "none" && !baseTheme.gradient ? "off" : "on";
  const props = ["--bg", "--panel", "--surface", "--surface-2", "--ember", "--ember-strong", "--ember-soft", "--accent-rgb", "--theme-gradient", "--theme-wallpaper", "--theme-font", "--theme-card-radius", "--theme-nav-radius", "--theme-window-shape", "--text", "--text-2", "--muted", "--theme-wallpaper-dim", "--theme-panel-opacity"];
  props.forEach(prop => root.style.removeProperty(prop));

  let palette = {
    accent: appearance.accent || baseTheme.accent, background: appearance.background || baseTheme.background,
    panel: appearance.panel || baseTheme.panel, surface: appearance.surface || baseTheme.surface,
  };
  let imageId = appearance.imageId;
  let opacity = 1;
  let darkness = 0;
  let position = "center";
  let localFont: string | null = null;
  let strongColor: string | null = null;
  root.dataset.wallpaper = "off";
  root.dataset.localPreset = "";
  root.dataset.officialPreset = "";
  root.dataset.officialTheme = "";
  root.dataset.windowShape = "off";
  if (appearance.officialThemeId) {
    const official = officialPalette(appearance.officialThemeId);
    const group = officialGroupFor(appearance.officialThemeId);
    if (official && group) {
      palette = { background: official.surface, panel: official.raised, surface: official.surface, accent: official.accent };
      strongColor = official.strong;
      root.dataset.officialPreset = group.id;
      root.dataset.officialTheme = appearance.officialThemeId;
      opacity = .8;
      darkness = group.id === "cyberpunk" ? 40 : 30;
      if (group.id === "cyberpunk") {
        root.style.setProperty("--theme-card-radius", "4px 16px 4px 16px");
        root.style.setProperty("--theme-nav-radius", "4px 14px 4px 14px");
      } else if (group.id === "naruto") {
        root.style.setProperty("--theme-card-radius", appearance.officialThemeId === "hinata" ? "12px 5px 12px 5px" : "5px 20px 5px 20px");
        root.style.setProperty("--theme-nav-radius", appearance.officialThemeId === "hinata" ? "12px 5px 12px 5px" : "4px 16px 4px 16px");
      }
    }
  }
  if (hash(appearance.localThemeId) && "__TAURI_INTERNALS__" in window) {
    try {
      const themes = await invoke<LocalTheme[]>("list_local_themes");
      if (request !== latestRequest) return;
      const theme = themes.find(item => item.id === appearance.localThemeId);
      const variant = theme?.variants[appearance.localThemeVariant] || theme?.variants[0];
      if (variant) {
        root.dataset.localPreset = variant.preset;
        const colors = variant.appearance?.palette;
        if (colors && [colors.surface, colors.raised, colors.accent, colors.strong].every(hex)) {
          palette = { background: colors.surface, panel: colors.raised, surface: colors.surface, accent: colors.accent };
          strongColor = colors.strong;
        }
        const cardRadius = variant.appearance?.geometry?.cardRadius;
        const navRadius = variant.appearance?.geometry?.navigationRadius;
        const windowShape = variant.appearance?.geometry?.window;
        if (typeof windowShape === "string" && windowShape.length <= 180 && /^(?:inset|polygon)\([0-9.%(),\s+\-calcrondpx]+\)$/.test(windowShape) && CSS.supports("clip-path", windowShape)) {
          root.style.setProperty("--theme-window-shape", windowShape);
          root.dataset.windowShape = "on";
        }
        if (typeof cardRadius === "string" && /^[0-9.px% /]+$/.test(cardRadius)) root.style.setProperty("--theme-card-radius", cardRadius);
        if (typeof navRadius === "string" && /^[0-9.px% /]+$/.test(navRadius)) root.style.setProperty("--theme-nav-radius", navRadius);
        const font = variant.appearance?.font;
        if (typeof font === "string" && font.length <= 100 && /^[a-z0-9 "',-]+$/i.test(font)) localFont = font;
        // The full-size artwork can exceed 10 MB as a data URL. The package's
        // medium rendition is intended for the application window.
        imageId = variant.medium || variant.compact || variant.image;
        opacity = Math.max(.6, Math.min(1, variant.panelOpacity / 100));
        darkness = Math.max(30, Math.min(85, variant.darkness));
        if (["center", "left", "right"].includes(variant.position)) position = variant.position;
      }
    } catch { /* A package may have been removed between launches. */ }
  }
  if (hex(palette.background)) root.style.setProperty("--bg", palette.background);
  if (appearance.localThemeId || appearance.officialThemeId) {
    root.style.setProperty("--text", "#f3f4f6");
    root.style.setProperty("--text-2", "#b9c1c8");
    root.style.setProperty("--muted", "#a0abb5");
  }
  if (hex(palette.panel)) root.style.setProperty("--panel", opacity < 1 ? rgba(palette.panel, opacity) : palette.panel);
  if (hex(palette.surface)) {
    root.style.setProperty("--surface", palette.surface);
    root.style.setProperty("--surface-2", hex(palette.panel) ? palette.panel : palette.surface);
  }
  if (hex(palette.accent)) {
    root.style.setProperty("--ember", palette.accent);
    root.style.setProperty("--ember-strong", strongColor || palette.accent);
    root.style.setProperty("--ember-soft", rgba(palette.accent, .14));
    root.style.setProperty("--accent-rgb", palette.accent.slice(1).match(/../g)!.map(part => parseInt(part, 16)).join(","));
  }
  root.style.setProperty("--theme-font", appearance.font === "serif" ? 'Georgia, "Times New Roman", serif' : appearance.font === "mono" ? 'Consolas, "Cascadia Code", monospace' : localFont || '"Segoe UI", sans-serif');
  const gradient = gradients[appearance.gradient];
  if (gradient) root.style.setProperty("--theme-gradient", `linear-gradient(${Math.min(360, Math.max(0, appearance.gradientAngle))}deg, ${gradient[0]}, ${gradient[1]})`);
  else if (baseTheme.gradient) root.style.setProperty("--theme-gradient", baseTheme.gradient);
  root.style.setProperty("--theme-wallpaper-position", position);
  root.style.setProperty("--theme-panel-opacity", `${Math.round(opacity * 100)}%`);
  root.style.setProperty("--theme-wallpaper-dim", `linear-gradient(rgba(0,0,0,${darkness / 100}),rgba(0,0,0,${darkness / 100}))`);
  let customStyle = document.getElementById("sftranslator-custom-theme") as HTMLStyleElement | null;
  if (!customStyle) {
    customStyle = document.createElement("style");
    customStyle.id = "sftranslator-custom-theme";
    document.head.appendChild(customStyle);
  }
  try { customStyle.textContent = compileCustomCss(appearance.customCss); }
  catch { customStyle.textContent = ""; }
  if (hash(imageId) && "__TAURI_INTERNALS__" in window) {
    try {
      const data = cachedImage?.id === imageId ? cachedImage.data : await invoke<string>("read_theme_image", { id: imageId });
      if (request !== latestRequest) return;
      if (data.startsWith("data:image/png;base64,") || data.startsWith("data:image/gif;base64,")) {
        cachedImage = { id: imageId, data };
        root.style.setProperty("--theme-wallpaper", `url("${data}")`);
        root.dataset.wallpaper = "on";
      }
    } catch { /* Missing image falls back to the selected palette. */ }
  }
}
