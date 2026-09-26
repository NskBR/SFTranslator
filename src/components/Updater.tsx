import { useCallback, useEffect, useState } from "react";
import { getVersion } from "@tauri-apps/api/app";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { ArrowDownToLine, ExternalLink, RefreshCw, X } from "lucide-react";
import packageInfo from "../../package.json";

type UpdateInfo = {
  available: boolean;
  current_version: string;
  latest_version: string;
  release_url: string;
  release_name: string | null;
  release_notes: string | null;
  installer_name: string | null;
  installer_size: number | null;
  install_supported: boolean;
};

type UpdateProgress = {
  status: "idle" | "downloading" | "cancelling" | "ready" | "installing" | "failed";
  downloaded_bytes: number;
  total_bytes: number | null;
  installer_name: string | null;
  message: string | null;
};

const idle: UpdateProgress = { status: "idle", downloaded_bytes: 0, total_bytes: null, installer_name: null, message: null };
const inTauri = "__TAURI_INTERNALS__" in window;
const size = (bytes?: number | null) => bytes == null ? "" : `${(bytes / 1024 / 1024).toFixed(1)} MB`;

export function useUpdater() {
  const [version, setVersion] = useState(packageInfo.version);
  const [info, setInfo] = useState<UpdateInfo | null>(null);
  const [progress, setProgress] = useState<UpdateProgress>(idle);
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);

  const check = useCallback(async (manual = false) => {
    if (!inTauri) return;
    setChecking(true);
    setError(null);
    try {
      const result = await invoke<UpdateInfo>("check_for_updates");
      setInfo(result);
      if (manual) setOpen(true);
    } catch (cause) {
      if (manual) {
        setError(String(cause));
        setOpen(true);
      }
    } finally {
      setChecking(false);
    }
  }, []);

  useEffect(() => {
    if (!inTauri) return;
    getVersion().then(setVersion).catch(() => undefined);
    invoke<UpdateProgress>("update_download_status").then(status => {
      setProgress(status);
      if (status.status === "failed") setOpen(true);
    }).catch(() => undefined);
    void check();
    let unlisten: (() => void) | undefined;
    listen<UpdateProgress>("update-download-progress", event => setProgress(event.payload))
      .then(stop => { unlisten = stop; });
    return () => unlisten?.();
  }, [check]);

  const act = async (command: string) => {
    setError(null);
    try {
      await invoke(command);
      if (command === "download_update") setProgress({ status: "downloading", downloaded_bytes: 0, total_bytes: info?.installer_size ?? null, installer_name: info?.installer_name ?? null, message: null });
    } catch (cause) { setError(String(cause)); }
  };

  return { version, info, progress, checking, error, open, setOpen, check, act };
}

export type Updater = ReturnType<typeof useUpdater>;

export function UpdateSettingsRow({ updater }: { updater: Updater }) {
  return <div className="update-settings-row">
    <div><h3>Atualizações do aplicativo</h3><p>Versão {updater.version} · {updater.info?.available ? `Nova versão ${updater.info.latest_version} disponível` : updater.info ? "Você está na versão mais recente" : "Verifique no GitHub quando desejar"}</p></div>
    <button type="button" className="secondary" disabled={updater.checking} onClick={() => void updater.check(true)}><RefreshCw size={14} className={updater.checking ? "spin" : undefined}/>{updater.checking ? "Verificando…" : "Verificar agora"}</button>
  </div>;
}

export function UpdateModal({ updater, gameRunning }: { updater: Updater; gameRunning: boolean }) {
  if (!updater.open) return null;
  const { info, progress } = updater;
  const busy = progress.status === "downloading" || progress.status === "cancelling" || progress.status === "installing";
  const percentage = progress.total_bytes && progress.total_bytes > 0 ? Math.min(100, Math.round(progress.downloaded_bytes / progress.total_bytes * 100)) : 0;
  return <div className="modal-backdrop" onMouseDown={event => { if (event.target === event.currentTarget && !busy) updater.setOpen(false); }}>
    <section className="update-modal" role="dialog" aria-modal="true" aria-labelledby="update-title">
      <button type="button" className="modal-close" aria-label="Fechar" onClick={() => updater.setOpen(false)}><X size={18}/></button>
      <span className="eyebrow">ATUALIZAÇÕES</span>
      <h2 id="update-title">{updater.error || progress.status === "failed" ? "Não foi possível atualizar" : info?.available ? `SFTranslator ${info.latest_version}` : info ? "SFTranslator atualizado" : "Verificar atualizações"}</h2>
      <p className="update-summary">{updater.error || progress.status === "failed" ? updater.error || progress.message : info?.available ? `Versão instalada: ${info.current_version}. ${info.installer_size ? `Instalador: ${size(info.installer_size)}.` : ""}` : info ? `A versão ${info.current_version} já é a mais recente publicada.` : "Não foi possível consultar as versões publicadas."}</p>
      {info?.available && info.release_notes && <div className="update-notes"><b>Notas da versão</b><p>{info.release_notes}</p></div>}
      {progress.status === "downloading" && <div className="update-download"><div><span>Baixando e verificando o instalador</span><b>{percentage}%</b></div><div className="progress-track"><i style={{ width: `${percentage}%` }}/></div><small>{size(progress.downloaded_bytes)} / {size(progress.total_bytes)}</small></div>}
      {progress.status === "cancelling" && <p className="update-note">Cancelando download…</p>}
      {progress.status === "ready" && <p className="update-note">Download concluído. O instalador passou na verificação SHA-256.</p>}
      {gameRunning && progress.status === "ready" && <p className="update-note warning">Encerre o jogo antes de instalar a atualização.</p>}
      {info?.available && !info.installer_name && <p className="update-note warning">Esta versão ainda não tem um instalador NSIS x64 verificável. Abra o release para baixar manualmente.</p>}
      {info?.available && !info.install_supported && <p className="update-note">A instalação automática está disponível no aplicativo instalado, fora do modo de desenvolvimento.</p>}
      <footer>
        {info?.available && <button type="button" className="secondary" onClick={() => void updater.act("open_release_page")}><ExternalLink size={15}/>Ver release</button>}
        {progress.status === "downloading" && <button type="button" className="secondary" onClick={() => void updater.act("cancel_update_download")}>Cancelar download</button>}
        {info?.available && info.installer_name && info.install_supported && (progress.status === "idle" || progress.status === "failed") && <button type="button" className="primary" onClick={() => void updater.act("download_update")}><ArrowDownToLine size={16}/>Baixar atualização</button>}
        {progress.status === "ready" && <button type="button" className="primary" disabled={gameRunning} onClick={() => void updater.act("install_downloaded_update")}>Instalar e reiniciar</button>}
        {!busy && <button type="button" className="secondary" onClick={() => updater.setOpen(false)}>Fechar</button>}
      </footer>
    </section>
  </div>;
}
