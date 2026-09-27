import { Fragment, useEffect, useMemo, useRef, useState, type MouseEvent as ReactMouseEvent } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { confirm, open } from "@tauri-apps/plugin-dialog";
import "country-flag-icons/3x2/flags.css";
import logo from "./assets/sftranslator-logo-v2.png";
import {
  Activity, Box, ChevronLeft, ChevronRight, CircleHelp, Download, Gamepad2,
  ChevronDown, Languages, LayoutGrid, Library, List, Maximize2, Minus, Play, Plus, Search,
  Settings, Trash2, Wrench, X, Pencil, Terminal, Square
} from "lucide-react";
import type { AppSettings, EngineHealth, Game, TranslationModel } from "./types";
import type { DownloadTask, SessionLine } from "./types";
import { DeleteGameModal } from "./components/Common";
import { UpdateModal, UpdateSettingsRow, useUpdater } from "./components/Updater";
import { LibraryPage } from "./pages/LibraryPage";
import { GameDetails, Wizard } from "./pages/GameConfig";
import { Models } from "./pages/Models";
import { Diagnostics, DownloadsPage, EmptyPage, SessionPage, SettingsPage } from "./pages/UtilityPages";
import { isTestOnlyGame } from "./engines";

const navigation = [
  ["Biblioteca", Library], ["Console", Terminal],
  ["Modelos", Box], ["Downloads", Download], ["Diagnósticos", Activity]
] as const;

const DEFAULT_SIDEBAR_WIDTH = 240;
const COMPACT_SIDEBAR_WIDTH = 68;
const MIN_SIDEBAR_WIDTH = 140;
const MAX_SIDEBAR_WIDTH = 260;

function App() {
  const updater = useUpdater();
  const [page, setPage] = useState("Biblioteca");
  const [games, setGames] = useState<Game[]>([]);
  const [health, setHealth] = useState<EngineHealth[]>([]);
  const [models, setModels] = useState<TranslationModel[]>([]);
  const [settings, setSettings] = useState<AppSettings>({ enableExperimentalChainedFlow: false });
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("Todos");
  const [toast, setToast] = useState<string>();
  const [selectedGame, setSelectedGame] = useState<Game>();
  const [downloads, setDownloads] = useState<DownloadTask[]>([]);
  const [sessionGame, setSessionGame] = useState<Game>();
  const [gamePendingDeletion, setGamePendingDeletion] = useState<Game>();
  const [sessionLines, setSessionLines] = useState<SessionLine[]>([]);
  const [sessionRunning, setSessionRunning] = useState(false);
  const sidebarRef = useRef<HTMLElement>(null);
  const [sidebarWidth, setSidebarWidth] = useState(() => {
    try {
      const saved = Number(localStorage.getItem("sftranslator_sidebar_width_v2"));
      if (Number.isFinite(saved) && saved > 0) {
        if (saved <= 90) return COMPACT_SIDEBAR_WIDTH;
        return Math.min(Math.max(saved, MIN_SIDEBAR_WIDTH), MAX_SIDEBAR_WIDTH);
      }
    } catch { /* localStorage pode estar indisponível no preview web */ }
    return DEFAULT_SIDEBAR_WIDTH;
  });
  const [isResizingSidebar, setIsResizingSidebar] = useState(false);
  const isSidebarCompact = sidebarWidth <= 90;
  const inTauri = "__TAURI_INTERNALS__" in window;
  const appWindow = inTauri ? getCurrentWindow() : undefined;

  const refresh = async () => {
    const results = await Promise.allSettled([
      invoke<Game[]>("list_games").then(setGames),
      invoke<EngineHealth[]>("engine_health").then(setHealth),
      invoke<TranslationModel[]>("list_models").then(setModels),
      invoke<AppSettings>("get_settings").then(setSettings),
    ]);
    const errors = results.filter(result => result.status === "rejected");
    if (errors.length) throw new Error(errors.map(result => String(result.reason)).join("; "));
  };
  useEffect(() => {
    if (inTauri) refresh().catch(e => setToast(String(e)));
    else setHealth([
      { engine: "Ren'Py", sourceFound: true, runtimeFound: true, modelFound: true, details: "Hook moderno e legado; servidor local LibreTranslate/Argos." },
      { engine: "Unity", sourceFound: true, runtimeFound: true, modelFound: false, details: "Instalador BepInEx/XUnity para Mono e IL2CPP." },
      { engine: "RPG Maker", sourceFound: true, runtimeFound: true, modelFound: false, development: true, details: "MV/MZ e Unite com hooks experimentais; versões antigas com OCR local e sobreposição em teste." },
      { engine: "Unreal", sourceFound: true, runtimeFound: true, modelFound: false, development: true, details: "Observador de texto experimental para CatIslandPetrichor; tradução ainda não implementada." }
    ]);
  }, []);
  useEffect(() => {
    if (!isResizingSidebar) return;

    const move = (event: MouseEvent) => {
      const sidebar = sidebarRef.current;
      if (!sidebar) return;
      const rawWidth = event.clientX - sidebar.getBoundingClientRect().left;
      const nextWidth = rawWidth < 115
        ? COMPACT_SIDEBAR_WIDTH
        : Math.min(Math.max(rawWidth, MIN_SIDEBAR_WIDTH), MAX_SIDEBAR_WIDTH);
      setSidebarWidth(nextWidth);
      try { localStorage.setItem("sftranslator_sidebar_width_v2", String(nextWidth)); } catch { /* noop */ }
    };
    const stop = () => setIsResizingSidebar(false);

    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", stop);
    return () => {
      window.removeEventListener("mousemove", move);
      window.removeEventListener("mouseup", stop);
    };
  }, [isResizingSidebar]);

  const startSidebarResize = (event: ReactMouseEvent) => {
    event.preventDefault();
    setIsResizingSidebar(true);
  };

  const toggleSidebarWidth = () => {
    const nextWidth = isSidebarCompact ? DEFAULT_SIDEBAR_WIDTH : COMPACT_SIDEBAR_WIDTH;
    setSidebarWidth(nextWidth);
    try { localStorage.setItem("sftranslator_sidebar_width_v2", String(nextWidth)); } catch { /* noop */ }
  };
  useEffect(() => {
    if (!inTauri) return;
    const cleanups = Promise.all([
      listen<{modelId:string;progress:number}>("model-download-progress", event => setDownloads(tasks => tasks.map(task => task.modelId === event.payload.modelId ? {...task, progress:event.payload.progress, detail:event.payload.progress < 100 ? `Baixando pacote… ${event.payload.progress}%` : "Finalizando instalação…"} : task))),
      listen<SessionLine>("session-log", event => setSessionLines(lines => [...lines.slice(-499), event.payload])),
      listen<{code:number}>("session-ended", event => { setSessionRunning(false); setSessionLines(lines => [...lines, {kind:"system",text:`Processo encerrado com código ${event.payload.code}.`}]); })
    ]);
    return () => { cleanups.then(items => items.forEach(cleanup => cleanup())); };
  }, []);
  useEffect(() => {
    if (!toast) return;
    const timeout = window.setTimeout(() => setToast(undefined), 4500);
    return () => window.clearTimeout(timeout);
  }, [toast]);
  useEffect(() => {
    if (!appWindow) return;
    appWindow.setAlwaysOnTop(sessionRunning).catch(() => undefined);
    return () => { appWindow.setAlwaysOnTop(false).catch(() => undefined); };
  }, [appWindow, sessionRunning]);

  const addGame = async (engineHint?: string): Promise<Game | undefined> => {
    const selected = await open({ multiple: false, filters: [{ name: "Executável do jogo", extensions: ["exe"] }] });
    if (!selected) return undefined;
    try {
      const game = await invoke<Game>("add_game", { executablePath: selected, engineHint });
      await refresh();
      setToast(`${game.name} adicionado como ${game.engine}.`);
      return game;
    } catch (e) { setToast(String(e)); return undefined; }
  };

  const beginAddGame = async (engineHint?: string) => {
    setSelectedGame(undefined);
    const game = await addGame(engineHint);
    if (!game) return;
    if (game.engine === "Unreal" && isTestOnlyGame(game)) {
      setPage("Biblioteca");
      setToast(`${game.name} cadastrado para teste de reconhecimento. A tradução Unreal ainda não está disponível.`);
      return;
    }
    setSelectedGame(game);
    setPage("Adicionar jogo");
  };

  const configureGame = async (game: Game, sourceLanguage: string, targetLanguage: string, flowMode: "direct"|"chain", intermediateLanguage?: string, rpgMakerFamily?: string) => {
    try {
      const testOnly = isTestOnlyGame({...game,runtime:rpgMakerFamily||game.runtime});
      const pairs = flowMode === "chain" ? [[sourceLanguage, "en"], ["en", targetLanguage]] : [[sourceLanguage, targetLanguage]];
      for (const [from, to] of pairs) {
        const requiredModel = models.find(model => model.fromCode === from && model.toCode === to);
        if (!requiredModel) throw new Error(`Fluxo indisponível: ${from.toUpperCase()} → ${to.toUpperCase()}`);
        if (!testOnly && !requiredModel.installed && !await downloadModel(requiredModel)) return;
      }
      const updated = await invoke<Game>("configure_game", { gameId: game.id, sourceLanguage, targetLanguage, flowMode, intermediateLanguage, rpgMakerFamily });
      await refresh(); setSelectedGame(undefined); setPage("Biblioteca");
      setToast(testOnly ? "Escolha uma versão compatível para testar a tradução." : game.engine === "Unreal" ? "Fluxo Unreal experimental salvo. O hook será atualizado ao iniciar o jogo." : game.engine === "RPG Maker" ? ["95","2000/2003","XP","VX","VX Ace"].includes(rpgMakerFamily||game.runtime||"") ? `Fluxo ${rpgMakerFamily} salvo. O OCR local experimental será iniciado com o jogo.` : `Fluxo ${rpgMakerFamily||game.runtime} experimental salvo. A integração será instalada ao iniciar o jogo.` : updated.modelInstalled ? "Configuração salva. O fluxo está disponível." : "Configuração salva. Baixe o fluxo necessário em Modelos.");
    } catch (e) { setToast(String(e)); }
  };

  const updateSettings = async (next: AppSettings) => {
    try { setSettings(await invoke<AppSettings>("update_settings", { settings: next })); }
    catch (error) { setToast(String(error)); }
  };

  const deleteModel = async (model: TranslationModel) => {
    if (!await confirm(`Jogos dependentes voltarão ao estado “Modelo necessário”.`, { title: `Apagar ${model.fromName} → ${model.toName}?`, kind: "warning" })) return;
    try { await invoke("delete_model", { modelId: model.id }); await refresh(); setToast("Modelo removido e jogos dependentes atualizados."); }
    catch (e) { setToast(String(e)); }
  };

  async function downloadModel(model: TranslationModel) {
    const id = `${model.id}-${Date.now()}`;
    setDownloads(tasks => [{ id, modelId:model.id, name: `${model.fromName} → ${model.toName}`, status: "baixando", detail: "Conectando ao catálogo Argos…", progress:0 }, ...tasks]);
    setPage("Downloads");
    try {
      await invoke("download_model", { modelId: model.id });
      await refresh();
      setDownloads(tasks => tasks.map(task => task.id === id ? {...task, status:"concluído", detail:"Modelo instalado e disponível para todos os jogos.", progress:100} : task));
      setToast(`Modelo ${model.fromName} → ${model.toName} instalado.`);
      return true;
    } catch (e) {
      setDownloads(tasks => tasks.map(task => task.id === id ? {...task, status:"erro", detail:String(e)} : task));
      setToast(String(e));
      return false;
    }
  }

  const launchGame = async (game: Game) => {
    if (sessionRunning) {
      setPage("Console");
      if (sessionGame?.id !== game.id) setToast(`Já existe uma sessão ativa: ${sessionGame?.name}. Encerre o jogo antes de iniciar outro.`);
      return;
    }
    setSessionGame(game); setSessionLines([]); setSessionRunning(true); setPage("Console");
    try { await invoke("launch_game", { gameId: game.id }); await refresh(); }
    catch (e) { setSessionRunning(false); setSessionLines([{kind:"error",text:String(e)}]); }
  };
  const stopGame = async () => {
    try {
      await invoke("stop_game_session");
      setToast("Encerrando o jogo…");
    } catch (e) { setToast(String(e)); }
  };

  const removeGame = async (game: Game) => {
    try {
      await invoke("remove_game", { gameId: game.id });
      setSelectedGame(undefined);
      await refresh();
      setToast(`${game.name} foi removido da biblioteca.`);
    } catch (e) { setToast(String(e)); }
  };

  const openGameCache = async (game: Game) => {
    try { await invoke("open_game_cache", { gameId: game.id }); }
    catch (e) { setToast(String(e)); }
  };

  const clearGameCache = async (game: Game) => {
    if (sessionRunning && sessionGame?.id === game.id) {
      setToast("Encerre o jogo antes de limpar o cache deste fluxo.");
      return;
    }
    const flow = `${game.sourceLanguage.toUpperCase()} → ${game.flowMode === "chain" ? "EN → " : ""}${game.targetLanguage.toUpperCase()}`;
    if (!await confirm(`As traduções aprendidas para ${flow} serão removidas. Os modelos não serão apagados.`, { title: `Limpar cache de “${game.name}”?`, kind: "warning" })) return;
    try { await invoke("clear_game_cache", { gameId: game.id }); setToast("Cache de tradução limpo para este fluxo."); }
    catch (e) { setToast(String(e)); }
  };

  useEffect(() => {
    const pickers = Array.from(document.querySelectorAll<HTMLElement>(".installed-flow-list"));
    const cleanups: Array<() => void> = [];
    pickers.forEach(list => {
      const flowButtons = Array.from(list.querySelectorAll<HTMLButtonElement>(":scope > button"));
      const hiddenFlows = flowButtons.slice(2);
      if (!hiddenFlows.length) return;

      const dropdown = document.createElement("div");
      dropdown.className = "installed-flow-dropdown";
      const trigger = document.createElement("button");
      trigger.type = "button";
      trigger.className = "installed-flow-dropdown-trigger";
      trigger.textContent = `Outros modelos (${hiddenFlows.length})`;
      const menu = document.createElement("div");
      menu.className = "installed-flow-dropdown-menu";

      hiddenFlows.forEach(flow => {
        const labels = Array.from(flow.querySelectorAll("span")).map(item => item.textContent?.trim()).filter(Boolean);
        const option = document.createElement("button");
        option.type = "button";
        option.className = "installed-flow-dropdown-option";
        const flags = flow.querySelector(".flow-flags")?.cloneNode(true);
        if (flags) option.append(flags);
        const label = document.createElement("span");
        label.textContent = labels.length >= 2 ? `${labels[0]} → ${labels[1]}` : "Fluxo instalado";
        option.append(label);
        option.addEventListener("click", () => { flow.click(); menu.classList.remove("open"); });
        menu.append(option);
      });

      trigger.addEventListener("click", () => menu.classList.toggle("open"));
      dropdown.append(trigger, menu);
      list.append(dropdown);
      cleanups.push(() => dropdown.remove());
    });
    return () => cleanups.forEach(cleanup => cleanup());
  }, [page, selectedGame?.id, models]);

  const filtered = useMemo(() => games
    .filter(game => (filter === "Todos" || game.engine === filter) && game.name.toLowerCase().includes(query.toLowerCase()))
    .sort((left, right) => {
      if (left.id === sessionGame?.id) return -1;
      if (right.id === sessionGame?.id) return 1;
      return (Date.parse(right.lastLaunch || "") || 0) - (Date.parse(left.lastLaunch || "") || 0);
    }), [games, query, filter, sessionGame?.id]);

  const openGameDetails = (game: Game) => {
    setSelectedGame(game);
    setPage("Biblioteca");
  };

  const installedModelCount = models.filter(model => model.installed).length;
  const contextText = page === "Biblioteca"
    ? `${games.length} ${games.length === 1 ? "jogo cadastrado" : "jogos cadastrados"} · ${installedModelCount} ${installedModelCount === 1 ? "modelo universal instalado" : "modelos universais instalados"}`
    : page === "Adicionar jogo"
      ? "O executável será analisado antes de qualquer instalação na pasta do jogo."
      : page === "Modelos"
        ? `${installedModelCount} de ${models.length} fluxos do catálogo estão instalados.`
        : page === "Downloads"
          ? `${downloads.filter(task => task.status === "baixando").length} em andamento · ${downloads.filter(task => task.status === "concluído").length} concluídos nesta sessão.`
          : page === "Console"
            ? sessionRunning ? sessionGame && isTestOnlyGame(sessionGame) ? "Jogo aberto para teste, sem tradução ativa." : "Preparação do motor, servidor local e tradução em execução." : "Sessão encerrada; o histórico permanece disponível."
            : "SFTranslator monitora os componentes locais dos motores integrados.";

  return <div className="shell">
    <header className="titlebar" data-tauri-drag-region onMouseDown={event => { if (event.button === 0 && !(event.target as HTMLElement).closest("button")) appWindow?.startDragging(); }} onDoubleClick={event => { if (!(event.target as HTMLElement).closest("button")) appWindow?.toggleMaximize(); }}>
      <div className="titlebar-engines">{health.map(item => { const engine=item.engine; const online=Boolean(item?.sourceFound&&item?.runtimeFound&&!item.development); return <span key={engine} title={item.details}><i className={`dot ${item.development?(item.runtimeFound?"warn":""):online?"ok":""}`}/>{item.development?`${engine==="RPG Maker"?"RPGM":engine} · dev`:engine}</span>; })}</div>
      <div className="app-title" data-tauri-drag-region><strong>SFTranslator</strong><span>v{updater.version}</span>{updater.info?.available && <button type="button" className="titlebar-update" onClick={() => updater.setOpen(true)}>Atualização v{updater.info.latest_version}</button>}</div>
      <div className="window-actions">
        <button onClick={() => appWindow?.minimize()} aria-label="Minimizar"><Minus size={16}/></button>
        <button onClick={() => appWindow?.toggleMaximize()} aria-label="Maximizar"><Maximize2 size={14}/></button>
        <button className="close" onClick={() => appWindow?.close()} aria-label="Fechar"><X size={17}/></button>
      </div>
    </header>
    <div className={`workspace ${isResizingSidebar ? "workspace-resizing" : ""}`}>
      <aside ref={sidebarRef} className={isSidebarCompact ? "sidebar-compact" : ""} style={{ width: sidebarWidth }}>
        <div className="sidebar-brand"><img src={logo} alt="SFTranslator"/></div>
        <nav>{navigation.map(([label, Icon],index) => <Fragment key={label}>{index===0&&<span className="nav-group-label">Biblioteca</span>}{index===2&&<span className="nav-group-label">Ferramentas</span>}<button title={isSidebarCompact ? label : undefined} className={page === label ? "active" : ""} onClick={() => setPage(label)}><Icon size={18}/><span>{label}</span>{label === "Biblioteca" && <b className="nav-count">{games.length}</b>}{label === "Console" && sessionRunning && <i className="console-live-dot" aria-label="Sessão ativa"/>}</button></Fragment>)}</nav>
        <section className="sidebar-overview"><span>VISÃO GERAL</span><div><button onClick={()=>setPage("Biblioteca")}><b>{games.length}</b><small>{games.length===1?"Jogo":"Jogos"}</small></button><button onClick={()=>setPage("Modelos")}><b>{installedModelCount}</b><small>{installedModelCount===1?"Modelo":"Modelos"}</small></button></div><p><i className={`dot ${sessionRunning?"ok":""}`}/>{sessionRunning?sessionGame&&isTestOnlyGame(sessionGame)?"Jogo aberto para teste":"Tradução em andamento":"Aplicativo pronto"}</p></section>
        <div className="sidebar-footer"><button className={page === "Configurações" ? "active" : ""} title="Configurações" onClick={() => setPage("Configurações")}><Settings size={18}/></button><button className={page === "Sobre" ? "active" : ""} title="Sobre" onClick={() => setPage("Sobre")}><CircleHelp size={18}/></button></div>
        <div className="sidebar-resizer" role="separator" aria-label="Redimensionar barra lateral" aria-orientation="vertical" onMouseDown={startSidebarResize} onDoubleClick={toggleSidebarWidth}/>
      </aside>
      <main>
        {page === "Biblioteca" && (selectedGame
          ? <GameDetails game={selectedGame} models={models} experimentalEnabled={settings.enableExperimentalChainedFlow} onBack={() => setSelectedGame(undefined)} onRemove={() => setGamePendingDeletion(selectedGame)} onSave={configureGame} onOpenCache={() => openGameCache(selectedGame)} onClearCache={() => clearGameCache(selectedGame)}/>
          : <LibraryPage games={filtered} engineNames={health.map(item=>item.engine)} filter={filter} setFilter={setFilter} query={query} setQuery={setQuery} onAddGame={() => beginAddGame()} onSelect={setSelectedGame} onLaunch={launchGame} onStop={stopGame} onDelete={setGamePendingDeletion} activeGameId={sessionRunning ? sessionGame?.id : undefined} onConsole={() => setPage("Console")}/>)}
        {page === "Adicionar jogo" && <Wizard existingGame={selectedGame} models={models} experimentalEnabled={settings.enableExperimentalChainedFlow} onSave={configureGame}/>}
        {page === "Modelos" && <Models models={models} games={games} onOpenGame={openGameDetails} onDelete={deleteModel} onDownload={downloadModel}/>} 
        {page === "Downloads" && <DownloadsPage tasks={downloads}/>} 
        {page === "Console" && sessionGame && (
          <SessionPage game={sessionGame} lines={sessionLines} running={sessionRunning} onBack={() => setPage("Biblioteca")} onRestart={() => launchGame(sessionGame)} onStop={stopGame}/>
        )}
        {page === "Console" && !sessionGame && <EmptyPage icon={Terminal} title="Console" text="Inicie um jogo pela biblioteca para acompanhar a instalação e a tradução. O histórico da última sessão fica disponível aqui enquanto o aplicativo estiver aberto."/>}
        {page === "Diagnósticos" && <Diagnostics health={health} onAddRpgMaker={() => beginAddGame("RPG Maker")} onAddUnreal={() => beginAddGame("Unreal")}/>}
        {page === "Configurações" && <SettingsPage settings={settings} onChange={updateSettings} updates={<UpdateSettingsRow updater={updater}/>}/>}
        {page === "Sobre" && <EmptyPage icon={Languages} title="SFTranslator" text="Uma biblioteca de tradução local para jogos compatíveis com os motores instalados."/>}
        <footer className="context-bar"><span><Activity size={14}/>{contextText}</span><b>{sessionRunning ? "Sessão ativa" : "Pronto"}</b></footer>
      </main>
    </div>
    {gamePendingDeletion && (
      <DeleteGameModal game={gamePendingDeletion} onCancel={() => setGamePendingDeletion(undefined)} onConfirm={() => { const game = gamePendingDeletion; setGamePendingDeletion(undefined); removeGame(game); }}/>
    )}
    <UpdateModal updater={updater} gameRunning={sessionRunning}/>
    {toast && <div className="toast" onClick={() => setToast(undefined)}>{toast}<X size={15}/></div>}
  </div>;
}

export default App;
