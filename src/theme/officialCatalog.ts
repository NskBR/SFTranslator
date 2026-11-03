export type OfficialAsset = { id: string; file: string; sha256: string; bytes: number };
export type OfficialPalette = { surface: string; raised: string; accent: string; strong: string };
export type OfficialVariant = { id: string; name: string; palette?: OfficialPalette };
export type OfficialGroup = { id: string; name: string; palette: OfficialPalette; variants: OfficialVariant[] };

const palette = (surface: string, raised: string, accent: string, strong: string): OfficialPalette => ({ surface, raised, accent, strong });
const variants = (ids: [string, string][]): OfficialVariant[] => ids.map(([id, name]) => ({ id, name }));

// The image IDs and palettes correspond to the SFDownloader catalog. Images are
// downloaded from its GitHub repository only after the user selects a card.
export const officialGroups: OfficialGroup[] = [
  { id: "cyberpunk", name: "Cyberpunk", palette: palette("#281b2b", "#402338", "#ff416b", "#ff7191"), variants: [
    { id: "cyberpunk", name: "Songbird" },
    { id: "cyberpunk--v-sunset", name: "V · Sunset", palette: palette("#2c1c1d", "#472b2b", "#f58b73", "#ffd0b5") },
    { id: "cyberpunk--v-inferno", name: "V · Inferno", palette: palette("#241c18", "#3c2a20", "#ff943d", "#ffd080") },
  ] },
  { id: "cs2", name: "Counter-Strike 2", palette: palette("#26221d", "#383027", "#ec9639", "#ffac45"), variants: variants([["cs2", "Original"]]) },
  { id: "star-citizen", name: "Star Citizen", palette: palette("#112633", "#1d394b", "#61bee7", "#b8e7ff"), variants: variants([["star-citizen", "Original"]]) },
  { id: "god-of-war-ragnarok", name: "God of War Ragnarök", palette: palette("#202d34", "#30434d", "#9dc8e2", "#dceefa"), variants: variants([["god-of-war-ragnarok", "Original"]]) },
  { id: "valorant", name: "Valorant", palette: palette("#2c1c26", "#402a36", "#ff5969", "#ffc0c7"), variants: variants([["valorant", "Original"]]) },
  { id: "league-of-legends", name: "League of Legends", palette: palette("#152d33", "#273c40", "#c9a963", "#f2dba1"), variants: variants([["league-of-legends", "Original"]]) },
  { id: "overwatch", name: "Overwatch", palette: palette("#29313d", "#3b4757", "#f3a64d", "#ffdc9c"), variants: variants([["overwatch", "Original"]]) },
  { id: "among-us", name: "Among Us", palette: palette("#232340", "#35335a", "#86adff", "#d7e5ff"), variants: variants([["among-us", "Original"]]) },
  { id: "gta-6", name: "GTA VI", palette: palette("#32233b", "#49324f", "#fb8cb6", "#ffd0e2"), variants: variants([["gta-6", "Original"]]) },
  { id: "gta-san-andreas", name: "GTA San Andreas", palette: palette("#273025", "#394532", "#9ccc86", "#dcf1c5"), variants: [
    { id: "gta-san-andreas", name: "Vinewood" },
    { id: "gta-san-andreas--big-smoke", name: "Big Smoke", palette: palette("#26291c", "#3c4229", "#b8c885", "#e5e9bb") },
    { id: "gta-san-andreas--street-girl", name: "Los Santos", palette: palette("#202b25", "#35443a", "#b5d3a1", "#e0efce") },
    { id: "gta-san-andreas--grove-soldier", name: "Grove Street", palette: palette("#28291f", "#414234", "#c5c19d", "#eee7cc") },
    { id: "gta-san-andreas--lowrider", name: "Lowrider", palette: palette("#222c23", "#364535", "#afd18d", "#dcebb8") },
    { id: "gta-san-andreas--the-truth", name: "The Truth", palette: palette("#30241e", "#49352c", "#e5bb79", "#ffdfa1") },
    { id: "gta-san-andreas--bmx", name: "BMX", palette: palette("#1d2b2e", "#304449", "#a6d5d6", "#daeeee") },
    { id: "gta-san-andreas--orange-street", name: "Orange Street", palette: palette("#30231b", "#4a3425", "#e9ad69", "#ffe0af") },
    { id: "gta-san-andreas--grove-family", name: "Grove Family", palette: palette("#282d1e", "#3e472d", "#b6cc83", "#e5edbd") },
    { id: "gta-san-andreas--the-boss", name: "The Boss", palette: palette("#30221f", "#49302d", "#d5a078", "#f4cfab") },
  ] },
  { id: "the-last-of-us-2", name: "The Last of Us Part II", palette: palette("#222e28", "#334139", "#9cbda4", "#e0eddf"), variants: variants([["the-last-of-us-2", "Original"]]) },
  { id: "red-dead-redemption-2", name: "Red Dead Redemption 2", palette: palette("#34221e", "#4a3028", "#d79566", "#f2c49b"), variants: variants([["red-dead-redemption-2", "Original"]]) },
  { id: "minecraft", name: "Minecraft", palette: palette("#2b3522", "#3f4b30", "#a4c875", "#e0f0b6"), variants: variants([["minecraft", "Original"]]) },
  { id: "saitama", name: "OnePunchMan", palette: palette("#241e17", "#3a2a20", "#f0bd54", "#ffe1a2"), variants: [
    { id: "saitama", name: "Saitama" },
    { id: "saitama--genos", name: "Genos", palette: palette("#28201c", "#413027", "#ffb34f", "#ffe0a0") },
    { id: "saitama--tatsumaki", name: "Tatsumaki", palette: palette("#152a25", "#224438", "#63e9b1", "#c4ffe5") },
    { id: "saitama--fubuki", name: "Fubuki", palette: palette("#16282a", "#253c40", "#75d9d0", "#d5f7ef") },
  ] },
  { id: "naruto", name: "Naruto", palette: palette("#201713", "#3c281d", "#ffac50", "#ffd083"), variants: [
    { id: "naruto-baryon", name: "Modo Bárion" },
    { id: "hinata", name: "Hinata Hyuga", palette: palette("#19192c", "#2e2b47", "#c6b9f0", "#eee8ff") },
  ] },
];

const previewFiles = import.meta.glob<string>("../assets/official-themes/*preview.jpg", { eager: true, query: "?url", import: "default" });
export function officialPreview(id: string): string {
  const name = id === "hinata" ? "hinata--preview.jpg"
    : id.startsWith("saitama--") ? `one-punch-man--${id.slice(9)}-preview.jpg`
    : `${id}-preview.jpg`;
  return previewFiles[`../assets/official-themes/${name}`] || "";
}

export function officialPalette(id: string): OfficialPalette | undefined {
  const group = officialGroups.find(item => item.variants.some(variant => variant.id === id));
  const variant = group?.variants.find(item => item.id === id);
  return variant?.palette || group?.palette;
}

export function officialGroupFor(id: string): OfficialGroup | undefined {
  return officialGroups.find(item => item.variants.some(variant => variant.id === id));
}
