import { useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { Check, ChevronDown, ChevronLeft, ChevronRight, ChevronUp, Gamepad2, RotateCcw, Trash2 } from "../components/icons";
import type { AppSettings } from "../types";
import { defaultAppearance } from "./presets";
import { officialGroups, officialPreview, type OfficialAsset } from "./officialCatalog";

export function OfficialThemes({ settings, onChange }: {
  settings: AppSettings; onChange: (value: AppSettings) => void;
}) {
  const appearance = { ...defaultAppearance, ...settings.appearance };
  const [assets, setAssets] = useState<OfficialAsset[]>([]);
  const [installed, setInstalled] = useState<string[]>([]);
  const [choices, setChoices] = useState<Record<string, number>>({});
  const [expanded, setExpanded] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const available = "__TAURI_INTERNALS__" in window;

  useEffect(() => {
    if (!available) return;
    let active = true;
    Promise.all([
      invoke<OfficialAsset[]>("official_theme_catalog"),
      invoke<string[]>("installed_official_themes"),
    ]).then(([catalog, saved]) => {
      if (active) { setAssets(catalog); setInstalled(saved); }
    }).catch(cause => { if (active) setError(String(cause)); });
    return () => { active = false; };
  }, [available]);

  const apply = async (id: string) => {
    const image = assets.find(asset => asset.id === `${id}-medium`);
    if (!image || busy) return;
    setBusy(id); setError(null);
    try {
      await invoke("download_official_theme", { id });
      setInstalled(current => [...new Set([...current, id])]);
      onChange({ ...settings, appearance: {
        ...appearance, officialThemeId: id, localThemeId: null, imageId: image.sha256,
        accent: null, background: null, panel: null, surface: null, gradient: "none",
      } });
    } catch (cause) { setError(String(cause)); }
    finally { setBusy(null); }
  };

  const remove = async (id: string) => {
    if (busy) return;
    setBusy(id); setError(null);
    try {
      await invoke("delete_official_theme", { id });
      setInstalled(current => current.filter(item => item !== id));
      if (appearance.officialThemeId === id) {
        onChange({ ...settings, appearance: { ...appearance, officialThemeId: null, imageId: null } });
      }
    } catch (cause) { setError(String(cause)); }
    finally { setBusy(null); }
  };

  const visible = expanded ? officialGroups : officialGroups.slice(0, 4);
  return <section className="settings-panel official-themes-panel">
    <div className="settings-panel-heading"><div className="settings-panel-icon"><Gamepad2 size={18}/></div><div><h2>Temas personalizados</h2><p>Baixe uma vez e aplique. Disponível offline após baixar.</p></div>{appearance.officialThemeId && <button type="button" className="secondary official-theme-reset" onClick={() => onChange({ ...settings, appearance: { ...appearance, officialThemeId: null, imageId: null } })}><RotateCcw size={14}/> Desativar</button>}</div>
    <div className="official-theme-grid">{visible.map(group => {
      const activeIndex = group.variants.findIndex(variant => variant.id === appearance.officialThemeId);
      const index = Math.max(0, Math.min(choices[group.id] ?? (activeIndex < 0 ? 0 : activeIndex), group.variants.length - 1));
      const variant = group.variants[index];
      const downloaded = installed.includes(variant.id);
      const selected = appearance.officialThemeId === variant.id;
      return <div className={`official-theme-card ${selected ? "selected" : ""}`} key={group.id}>
        <button type="button" className="official-theme-select" disabled={!available || busy !== null || assets.length === 0} onClick={() => void apply(variant.id)} aria-label={`${downloaded ? "Aplicar" : "Baixar"} ${group.name}: ${variant.name}`} aria-pressed={selected}>
          <span className="official-theme-preview">{officialPreview(variant.id) && <img src={officialPreview(variant.id)} alt="" loading="lazy" draggable={false}/>} {selected && <span className="official-theme-check"><Check size={13}/></span>}</span>
          <strong>{group.name}</strong><span className="official-theme-state">{busy === variant.id ? downloaded ? "Aplicando…" : "Baixando…" : selected ? "Baixado · Atual" : downloaded ? "Baixado · Aplicar" : "Clique para baixar"}</span>
        </button>
        {downloaded && <button type="button" className="official-theme-delete" aria-label={`Excluir tema ${group.name}: ${variant.name}`} title="Excluir imagens baixadas" disabled={busy !== null} onClick={() => void remove(variant.id)}><Trash2 size={14}/></button>}
        {group.variants.length > 1 && <div className="official-theme-variant"><button type="button" aria-label={`Variação anterior de ${group.name}`} disabled={busy !== null} onClick={() => setChoices(current => ({ ...current, [group.id]: (index - 1 + group.variants.length) % group.variants.length }))}><ChevronLeft size={16}/></button><span>{index + 1}/{group.variants.length} · {variant.name}</span><button type="button" aria-label={`Próxima variação de ${group.name}`} disabled={busy !== null} onClick={() => setChoices(current => ({ ...current, [group.id]: (index + 1) % group.variants.length }))}><ChevronRight size={16}/></button></div>}
      </div>;
    })}</div>
    <button type="button" className="secondary official-theme-expand" aria-expanded={expanded} onClick={() => setExpanded(value => !value)}>{expanded ? <ChevronUp size={15}/> : <ChevronDown size={15}/>} {expanded ? "Mostrar menos temas" : "Mostrar todos os temas"}</button>
    <p className="official-theme-note">Temas com imagens e transparência podem aumentar o uso de memória RAM e GPU. As imagens são baixadas do repositório SFDownloader-App e verificadas antes de serem usadas.</p>
    {error && <p className="official-theme-error" role="alert">{error}</p>}
  </section>;
}
