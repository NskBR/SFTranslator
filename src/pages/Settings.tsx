import { useEffect, useState, type ReactNode } from "react";
import { invoke } from "@tauri-apps/api/core";
import { FolderOpen, RefreshCw } from "../components/icons";
import { Languages, Palette } from "../components/icons";
import type { AppSettings } from "../types";
import { PageHeading } from "../components/Common";
import { AppearanceSettings } from "../theme/AppearanceSettings";

type SettingsTab = "appearance" | "translation" | "files" | "updates";
type StoragePaths = { data: string; models: string };

const tabs = [
  { id: "appearance", label: "Aparência", Icon: Palette },
  { id: "translation", label: "Tradução", Icon: Languages },
  { id: "files", label: "Arquivos", Icon: FolderOpen },
  { id: "updates", label: "Atualizações", Icon: RefreshCw },
] as const;

export function SettingsPage({ settings, onChange, updates, onError }: {
  settings: AppSettings;
  onChange: (settings: AppSettings) => void;
  updates: ReactNode;
  onError: (message: string) => void;
}) {
  const [activeTab, setActiveTab] = useState<SettingsTab>("appearance");
  const [paths, setPaths] = useState<StoragePaths>();

  useEffect(() => {
    if (activeTab !== "files" || paths || !("__TAURI_INTERNALS__" in window)) return;
    invoke<StoragePaths>("storage_paths").then(setPaths).catch(error => onError(String(error)));
  }, [activeTab, paths, onError]);

  const openFolder = async (kind: "data" | "models") => {
    try { await invoke("open_storage_folder", { kind }); }
    catch (error) { onError(String(error)); }
  };

  return <div className="page settings-page">
    <PageHeading title="Configurações" text="Ajuste a aparência, a tradução e os arquivos do aplicativo."/>
    <nav className="settings-tabs" aria-label="Categorias de configurações">
      {tabs.map(({ id, label, Icon }) => <button key={id} type="button" className={activeTab === id ? "active" : ""} aria-current={activeTab === id ? "page" : undefined} onClick={() => setActiveTab(id)}><Icon size={16}/><span>{label}</span></button>)}
    </nav>
    <div className="settings-content">
      {activeTab === "appearance" && <AppearanceSettings settings={settings} onChange={onChange} onError={onError}/>}

      {activeTab === "translation" && <div className="settings-grid">
        <section className="settings-panel">
          <div className="settings-panel-heading"><div className="settings-panel-icon"><Languages size={18}/></div><div><h2>Fluxo encadeado experimental</h2><p>Permite traduzir origem → inglês → destino usando dois modelos na mesma instância local.</p></div></div>
          <div className="settings-toggle-row"><div><b>Mostrar fluxo de três vias</b><span>Jogos já configurados continuam funcionando se esta opção for desligada.</span></div><button type="button" role="switch" aria-checked={settings.enableExperimentalChainedFlow} aria-label="Ativar fluxo encadeado experimental" className={`switch ${settings.enableExperimentalChainedFlow ? "on" : ""}`} onClick={() => onChange({ ...settings, enableExperimentalChainedFlow: !settings.enableExperimentalChainedFlow })}><i/></button></div>
        </section>
        <section className="settings-panel settings-info-panel"><h2>Modelos locais</h2><p>Os modelos de tradução são compartilhados entre os motores. Escolha e baixe os pares na aba Modelos; a configuração de cada jogo define quais pares serão usados.</p></section>
      </div>}

      {activeTab === "files" && <div className="settings-grid">
        <section className="settings-panel"><div className="settings-panel-heading"><div className="settings-panel-icon"><FolderOpen size={18}/></div><div><h2>Dados do aplicativo</h2><p>Biblioteca, preferências e arquivos de atualização.</p></div></div><code className="settings-path" title={paths?.data}>{paths?.data || "Carregando caminho…"}</code><button type="button" className="secondary" onClick={() => void openFolder("data")}>Abrir pasta</button></section>
        <section className="settings-panel"><div className="settings-panel-heading"><div className="settings-panel-icon"><FolderOpen size={18}/></div><div><h2>Modelos de tradução</h2><p>Arquivos Argos compartilhados pelos jogos configurados.</p></div></div><code className="settings-path" title={paths?.models}>{paths?.models || "Carregando caminho…"}</code><button type="button" className="secondary" onClick={() => void openFolder("models")}>Abrir pasta</button></section>
      </div>}

      {activeTab === "updates" && <section className="settings-panel settings-update-panel"><div className="settings-panel-heading"><div className="settings-panel-icon"><RefreshCw size={18}/></div><div><h2>Atualizações</h2><p>Consulte a versão publicada no GitHub e instale quando estiver pronto.</p></div></div>{updates}</section>}
    </div>
  </div>;
}
