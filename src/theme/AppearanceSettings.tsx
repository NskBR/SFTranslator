import { useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { open } from "@tauri-apps/plugin-dialog";
import { Check, ImagePlus, PackagePlus, Palette, Trash2 } from "../components/icons";
import type { AppSettings, ThemePreferences } from "../types";
import { defaultAppearance, themePresets, type LocalTheme, type ThemeImage } from "./presets";
import { compileCustomCss } from "./customCss";
import { OfficialThemes } from "./OfficialThemes";

export function AppearanceSettings({ settings, onChange, onError }: {
  settings: AppSettings; onChange: (value: AppSettings) => void; onError: (message: string) => void;
}) {
  const appearance = { ...defaultAppearance, ...settings.appearance };
  const [images, setImages] = useState<ThemeImage[]>([]);
  const [themes, setThemes] = useState<LocalTheme[]>([]);
  const [previews, setPreviews] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [cssDraft, setCssDraft] = useState(appearance.customCss);
  const available = "__TAURI_INTERNALS__" in window;
  const update = (change: Partial<ThemePreferences>) => onChange({ ...settings, appearance: { ...appearance, ...change } });
  const selectBaseTheme = (theme: AppSettings["theme"]) => onChange({ ...settings, theme, appearance: {
    ...appearance, accent: null, background: null, panel: null, surface: null,
    imageId: null, localThemeId: null, officialThemeId: null, gradient: "none", customCss: "",
  } });
  useEffect(() => setCssDraft(appearance.customCss), [appearance.customCss]);

  useEffect(() => {
    if (!available) return;
    Promise.all([invoke<ThemeImage[]>("list_theme_images"), invoke<LocalTheme[]>("list_local_themes")])
      .then(([loadedImages, loadedThemes]) => { setImages(loadedImages); setThemes(loadedThemes); })
      .catch(error => onError(String(error)));
  }, [available, onError]);

  useEffect(() => {
    if (!available || !themes.length) return;
    let cancelled = false;
    Promise.all(themes.map(async theme => {
      try { return [theme.id, await invoke<string>("read_theme_image", { id: theme.variants[0]?.preview })] as const; }
      catch { return [theme.id, ""] as const; }
    })).then(entries => { if (!cancelled) setPreviews(Object.fromEntries(entries)); });
    return () => { cancelled = true; };
  }, [available, themes]);

  const importAsset = async (kind: "image" | "zip") => {
    if (!available || busy) return;
    try {
      const path = await open({ multiple: false, filters: kind === "zip" ? [{ name: "Tema local", extensions: ["zip"] }] : [{ name: "Imagem", extensions: ["png", "gif"] }] });
      if (!path || typeof path !== "string") return;
      setBusy(true);
      if (kind === "zip") {
        const theme = await invoke<LocalTheme>("import_local_theme", { path });
        setThemes(await invoke<LocalTheme[]>("list_local_themes"));
        update({ localThemeId: theme.id, officialThemeId: null, localThemeVariant: 0, imageId: null });
      } else {
        const image = await invoke<ThemeImage>("import_theme_image", { path });
        setImages(await invoke<ThemeImage[]>("list_theme_images"));
        update({ imageId: image.id, localThemeId: null, officialThemeId: null });
      }
    } catch (error) { onError(String(error)); }
    finally { setBusy(false); }
  };

  const removeTheme = async (theme: LocalTheme) => {
    try {
      await invoke("delete_local_theme", { id: theme.id });
      setThemes(current => current.filter(item => item.id !== theme.id));
      if (appearance.localThemeId === theme.id) update({ localThemeId: null });
    } catch (error) { onError(String(error)); }
  };

  return <div className="appearance-settings">
    <section className="settings-panel base-themes-panel">
      <div className="settings-panel-heading"><div className="settings-panel-icon"><Palette size={18}/></div><div><h2>Tema do aplicativo</h2><p>Escolha o tema que define a aparência geral do app.</p></div><button type="button" className="secondary base-theme-reset" onClick={() => selectBaseTheme("amber")}>Restaurar tema padrão</button></div>
      <div className="theme-grid">{themePresets.map(theme => {
        const selected = settings.theme === theme.id && !appearance.localThemeId && !appearance.officialThemeId && !appearance.imageId && !appearance.accent && !appearance.customCss;
        return <button type="button" key={theme.id} className={`theme-tile ${selected ? "selected" : ""}`} aria-pressed={selected} onClick={() => selectBaseTheme(theme.id)}>
          {selected && <span className="base-theme-check"><Check size={12} strokeWidth={3}/></span>}
          <span className="theme-preview" style={{ background: theme.gradient || theme.background }}><span className="base-mini-sidebar"><i style={{ background: theme.accent }}/><i/><i/><i/></span><span className="base-mini-main"><i className="base-mini-topbar" style={{ background: theme.accent }}/><i className="base-mini-card"><em/><em/></i><i className="base-mini-card"><em/><em/></i></span><span className="base-mini-glow" style={{ background: theme.accent }}/></span>
          <span className="theme-caption"><b>{theme.name}</b><small>{selected ? "Atual" : "\u00a0"}</small></span>
        </button>;
      })}</div>
    </section>

    <section className="settings-panel">
      <div className="settings-panel-heading"><div className="settings-panel-icon"><ImagePlus size={18}/></div><div><h2>Imagem e gradiente</h2><p>Imagens locais ficam no armazenamento do app e funcionam offline.</p></div></div>
      <div className="appearance-inline"><label className="settings-field">Gradiente<select value={appearance.gradient} onChange={event => update({ gradient: event.target.value as ThemePreferences["gradient"] })}><option value="none">Nenhum</option><option value="aurora">Aurora</option><option value="sunset">Pôr do sol</option><option value="ocean">Oceano</option><option value="cyberpunk">Cyberpunk</option></select></label><label className="settings-field">Ângulo: {appearance.gradientAngle}°<input type="range" min="0" max="360" value={appearance.gradientAngle} onChange={event => update({ gradientAngle: Number(event.target.value) })}/></label></div>
      <div className="appearance-inline"><button className="secondary" type="button" disabled={!available || busy} onClick={() => void importAsset("image")}>Importar PNG/GIF</button><label className="settings-field">Imagem de fundo<select value={images.some(image => image.id === appearance.imageId) ? appearance.imageId! : ""} onChange={event => update({ imageId: event.target.value || null, localThemeId: null, officialThemeId: null })}><option value="">Nenhuma</option>{images.map(image => <option value={image.id} key={image.id}>{image.name}</option>)}</select></label></div>
    </section>

    <OfficialThemes settings={settings} onChange={onChange}/>

    <section className="settings-panel">
      <div className="settings-panel-heading"><div className="settings-panel-icon"><PackagePlus size={18}/></div><div><h2>Temas locais</h2><p>Importe um ZIP com theme.json e imagens PNG/GIF, no formato do SFDownloader.</p></div></div>
      <button className="secondary" type="button" disabled={!available || busy} onClick={() => void importAsset("zip")}>Adicionar tema local</button>
      <div className="local-theme-list">{themes.map(theme => <div className={`local-theme-row ${appearance.localThemeId === theme.id ? "selected" : ""}`} key={theme.id}>{previews[theme.id] && <img className="local-theme-preview" src={previews[theme.id]} alt=""/>}<button type="button" onClick={() => update({ localThemeId: theme.id, officialThemeId: null, localThemeVariant: 0, imageId: null })}><b>{theme.name}</b><small>{theme.author || "Autor não informado"} · {theme.variants.length} {theme.variants.length === 1 ? "variação" : "variações"}</small></button>{appearance.localThemeId === theme.id && <select aria-label="Variação do tema" value={appearance.localThemeVariant} onChange={event => update({ localThemeVariant: Number(event.target.value) })}>{theme.variants.map((variant, index) => <option key={index} value={index}>{variant.name}</option>)}</select>}<button type="button" className="local-theme-delete" aria-label={`Remover ${theme.name}`} onClick={() => void removeTheme(theme)}><Trash2 size={15}/></button></div>)}</div>
    </section>

    <section className="settings-panel">
      <div className="settings-panel-heading"><div className="settings-panel-icon"><Palette size={18}/></div><div><h2>Tipografia e movimento</h2><p>Os efeitos respeitam a preferência de movimento reduzido do sistema.</p></div></div>
      <label className="settings-field">Fonte<select value={appearance.font} onChange={event => update({ font: event.target.value as ThemePreferences["font"] })}><option value="system">Padrão do aplicativo</option><option value="serif">Serifada</option><option value="mono">Monoespaçada</option></select></label>
      <label className="settings-field">Estilo dos ícones<select value={appearance.iconStyle} onChange={event => update({ iconStyle: event.target.value as ThemePreferences["iconStyle"] })}><option value="default">Padrão</option><option value="accent">Cor de destaque</option><option value="soft">Suave</option></select></label>
      {([ ["animations", "Animações da interface"], ["animatedIcons", "Ícones animados"] ] as const).map(([key, label]) => <div className="settings-toggle-row" key={key}><div><b>{label}</b></div><button type="button" role="switch" aria-label={label} aria-checked={appearance[key]} className={`switch ${appearance[key] ? "on" : ""}`} onClick={() => update({ [key]: !appearance[key] })}><i/></button></div>)}
    </section>
    <section className="settings-panel appearance-css-panel">
      <div className="settings-panel-heading"><div className="settings-panel-icon"><Palette size={18}/></div><div><h2>CSS personalizado</h2><p>Regras visuais locais, limitadas a componentes e propriedades seguros.</p></div></div>
      <p>Seletores: <code>.game-card</code>, <code>.settings-panel</code>, <code>.model-card</code>, <code>aside nav button</code>, <code>.page-heading h1</code>, <code>.sidebar-overview</code>, <code>.theme-tile</code>.</p>
      <p>Propriedades: cor, fundo, borda, raio, espaçamento de letras e tamanho da fonte.</p>
      <textarea aria-label="CSS personalizado" value={cssDraft} maxLength={8192} spellCheck={false} placeholder={".game-card { border-radius: 16px; border-color: #445566; }"} onChange={event => setCssDraft(event.target.value)}/>
      <div className="appearance-css-actions"><button className="secondary" type="button" onClick={() => { try { compileCustomCss(cssDraft); update({ customCss: cssDraft }); } catch (error) { onError(String(error)); } }}>Aplicar CSS</button><button className="secondary" type="button" onClick={() => { setCssDraft(""); update({ customCss: "" }); }}>Limpar</button></div>
    </section>
  </div>;
}
