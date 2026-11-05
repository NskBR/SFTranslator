import { useEffect, useMemo, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { confirm, open } from "@tauri-apps/plugin-dialog";
import "country-flag-icons/3x2/flags.css";
import {
  Activity, ChevronLeft, ChevronRight, Gamepad2,
  ChevronDown, LayoutGrid, List, Play, Plus, Search,
  Trash2, Wrench, X, Pencil, Terminal, Square
} from "./components/icons";
import type { AppSettings, EngineHealth, Game, TranslationModel } from "./types";
import type { DownloadTask, SessionLine } from "./types";
import { DeleteGameModal } from "./components/Common";
import { AboutModal } from "./components/AboutModal";
import { UpdateModal, UpdateSettingsRow, useUpdater } from "./components/Updater";
import { LibraryPage } from "./pages/LibraryPage";
import { GameDetails, Wizard } from "./pages/GameConfig";
import { Models } from "./pages/Models";
import { Diagnostics, DownloadsPage, EmptyPage, SessionPage } from "./pages/UtilityPages";
import { SettingsPage } from "./pages/Settings";
import { MetricsPage } from "./pages/Metrics";
import { isTestOnlyGame } from "./engines";
import { applyTheme } from "./theme/applyTheme";
import { initialSettings } from "./theme/presets";
import { AppSidebar, AppTitlebar } from "./components/layout/AppChrome";
import { useLibraryPreferences } from "./hooks/useLibraryPreferences";
import { useSidebarWidth } from "./hooks/useSidebarWidth";

function App({ bootSettings }: { bootSettings?: AppSettings }) {
  const updater = useUpdater();
  const [page, setPage] = useState("Biblioteca");
  const [aboutOpen, setAboutOpen] = useState(false);
  const aboutButtonRef = useRef<HTMLButtonElement>(null);
  const [games, setGames] = useState<Game[]>([]);
  const [health, setHealth] = useState<EngineHealth[]>([]);
  const [models, setModels] = useState<TranslationModel[]>([]);
  const [settings, setSettings] = useState<AppSettings>(() => {
    if (bootSettings) return bootSettings;
    try {
      const cached = localStorage.getItem("sftranslator_theme");
      const theme = cached === "ocean" || cached === "violet" || cached === "contrast" || cached === "crimson" || cached === "forest" ? cached : "amber";
      return { ...initialSettings, theme };
    } catch { return initialSettings; }
  });
  const settingsSaveQueue = useRef<Promise<unknown>>(Promise.resolve());
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("Todos");
  const { view: libraryView, sort: librarySort, changeView: changeLibraryView, changeSort: changeLibrarySort } = useLibraryPreferences();
  const [toast, setToast] = useState<string>();
  const [selectedGame, setSelectedGame] = useState<Game>();
  const [downloads, setDownloads] = useState<DownloadTask[]>([]);
  const [sessionGame, setSessionGame] = useState<Game>();
  const [gamePendingDeletion, setGamePendingDeletion] = useState<Game>();
  const [sessionLines, setSessionLines] = useState<SessionLine[]>([]);
  const [sessionRunning, setSessionRunning] = useState(false);
  const { sidebarRef, width: sidebarWidth, resizing: isResizingSidebar, compact: isSidebarCompact, startResize: startSidebarResize, toggleWidth: toggleSidebarWidth } = useSidebarWidth();
  const inTauri = "__TAURI_INTERNALS__" in window;
  const appWindow = inTauri ? getCurrentWindow() : undefined;

  useEffect(() => {
    void applyTheme(settings);
    try { localStorage.setItem("sftranslator_theme", settings.theme); } catch { /* noop */ }
  }, [settings]);

  useEffect(() => {
    if (!inTauri) return;
    const current = getCurrentWindow();
    let live = true;
    const updateShape = async () => {
      const maximized = await current.isMaximized();
      if (live) document.documentElement.dataset.windowMaximized = maximized ? "true" : "false";
    };
    void updateShape();
    const resize = current.onResized(() => { void updateShape(); });
    return () => { live = false; void resize.then(unlisten => unlisten()); };
  }, [inTauri]);

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
      { engine: "RPG Maker", sourceFound: true, runtimeFound: true, modelFound: false, details: "MV/MZ e Unite com integração local; versões antigas com OCR local e sobreposição." },
      { engine: "Unreal", sourceFound: true, runtimeFound: true, modelFound: false, development: true, details: "Observador de texto experimental para CatIslandPetrichor; tradução ainda não implementada." }
    ]);
  }, []);
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
      setToast(testOnly ? "Jogo cadastrado para teste de reconhecimento." : game.engine === "Unreal" ? "Fluxo Unreal experimental salvo. O hook será atualizado ao iniciar o jogo." : game.engine === "RPG Maker" ? ["95","2000/2003","XP","VX","VX Ace"].includes(rpgMakerFamily||game.runtime||"") ? `Fluxo ${rpgMakerFamily} salvo. O OCR local será iniciado com o jogo.` : `Fluxo ${rpgMakerFamily||game.runtime} salvo. A integração será instalada ao iniciar o jogo.` : updated.modelInstalled ? "Configuração salva. O fluxo está disponível." : "Configuração salva. Baixe o fluxo necessário em Modelos.");
    } catch (e) { setToast(String(e)); }
  };

  const updateSettings = (next: AppSettings) => {
    setSettings(next);
    settingsSaveQueue.current = settingsSaveQueue.current.catch(() => undefined).then(() =>
      invoke<AppSettings>("update_settings", { settings: next })
    ).catch(error => { setToast(String(error)); });
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
    .filter(game => (filter === "Todos" || game.engine === filter) && game.name.toLocaleLowerCase().includes(query.toLocaleLowerCase()))
    .sort((left, right) => {
      if (sessionRunning && left.id === sessionGame?.id && right.id !== sessionGame?.id) return -1;
      if (sessionRunning && right.id === sessionGame?.id && left.id !== sessionGame?.id) return 1;
      if (librarySort.key === "name") {
        const compared = left.name.localeCompare(right.name, "pt-BR", { sensitivity: "base" });
        return (librarySort.direction === "asc" ? compared : -compared) || left.id.localeCompare(right.id);
      }
      const leftDate = Date.parse(left[librarySort.key] || "");
      const rightDate = Date.parse(right[librarySort.key] || "");
      if (!Number.isFinite(leftDate)) return Number.isFinite(rightDate) ? 1 : left.id.localeCompare(right.id);
      if (!Number.isFinite(rightDate)) return -1;
      const compared = librarySort.direction === "desc" ? rightDate - leftDate : leftDate - rightDate;
      return compared || left.id.localeCompare(right.id);
    }), [games, query, filter, librarySort, sessionRunning, sessionGame?.id]);

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
            : page === "Métricas"
              ? "Palavras e resultados registrados em sessões de tradução monitoradas."
            : "SFTranslator monitora os componentes locais dos motores integrados.";

  return <div className="shell">
    <AppTitlebar health={health} version={updater.version} updateVersion={updater.info?.available ? updater.info.latest_version : undefined} onUpdate={() => updater.setOpen(true)} onMinimize={() => { void appWindow?.minimize(); }} onMaximize={() => { void appWindow?.toggleMaximize(); }} onClose={() => { void appWindow?.close(); }} onDrag={() => { void appWindow?.startDragging(); }}/>
    <div className={`workspace ${isResizingSidebar ? "workspace-resizing" : ""}`}>
      <AppSidebar sidebarRef={sidebarRef} width={sidebarWidth} compact={isSidebarCompact} page={page} setPage={setPage} gamesCount={games.length} installedModelCount={installedModelCount} sessionRunning={sessionRunning} sessionGame={sessionGame} aboutOpen={aboutOpen} aboutButtonRef={aboutButtonRef} onAbout={() => setAboutOpen(true)} onResize={startSidebarResize} onToggleWidth={toggleSidebarWidth}/>
      <main>
        {page === "Biblioteca" && (selectedGame
          ? <GameDetails game={selectedGame} models={models} experimentalEnabled={settings.enableExperimentalChainedFlow} onBack={() => setSelectedGame(undefined)} onRemove={() => setGamePendingDeletion(selectedGame)} onSave={configureGame} onOpenCache={() => openGameCache(selectedGame)} onClearCache={() => clearGameCache(selectedGame)}/>
          : <LibraryPage games={filtered} hasGames={games.length > 0} engineNames={health.filter(item=>item.sourceFound&&item.runtimeFound).map(item=>item.engine)} engineAvailability={Object.fromEntries(health.map(item=>[item.engine,item.sourceFound&&item.runtimeFound]))} filter={filter} setFilter={setFilter} sort={librarySort} setSort={changeLibrarySort} view={libraryView} onViewChange={changeLibraryView} query={query} setQuery={setQuery} onAddGame={() => beginAddGame()} onSelect={setSelectedGame} onLaunch={launchGame} onStop={stopGame} onDelete={setGamePendingDeletion} activeGameId={sessionRunning ? sessionGame?.id : undefined} onConsole={() => setPage("Console")}/>)}
        {page === "Adicionar jogo" && <Wizard existingGame={selectedGame} models={models} experimentalEnabled={settings.enableExperimentalChainedFlow} onSave={configureGame}/>}
        {page === "Modelos" && <Models models={models} games={games} onOpenGame={openGameDetails} onDelete={deleteModel} onDownload={downloadModel}/>} 
        {page === "Downloads" && <DownloadsPage tasks={downloads}/>} 
        {page === "Console" && sessionGame && (
          <SessionPage game={sessionGame} lines={sessionLines} running={sessionRunning} onBack={() => setPage("Biblioteca")} onRestart={() => launchGame(sessionGame)} onStop={stopGame}/>
        )}
        {page === "Console" && !sessionGame && <EmptyPage icon={Terminal} title="Console" text="Inicie um jogo pela biblioteca para acompanhar a instalação e a tradução. O histórico da última sessão fica disponível aqui enquanto o aplicativo estiver aberto."/>}
        {page === "Diagnósticos" && <Diagnostics health={health} onAddRpgMaker={() => beginAddGame("RPG Maker")} onAddUnreal={() => beginAddGame("Unreal")}/>}
        {page === "Configurações" && <SettingsPage settings={settings} onChange={updateSettings} updates={<UpdateSettingsRow updater={updater}/>} onError={setToast}/>}
        {page === "Métricas" && <MetricsPage/>}
        <footer className="context-bar"><span><Activity size={14}/>{contextText}</span><b>{sessionRunning ? "Sessão ativa" : "Pronto"}</b></footer>
      </main>
    </div>
    {gamePendingDeletion && (
      <DeleteGameModal game={gamePendingDeletion} onCancel={() => setGamePendingDeletion(undefined)} onConfirm={() => { const game = gamePendingDeletion; setGamePendingDeletion(undefined); removeGame(game); }}/>
    )}
    {aboutOpen && <AboutModal
      version={updater.version}
      onClose={() => { setAboutOpen(false); aboutButtonRef.current?.focus(); }}
    />}
    <UpdateModal updater={updater} gameRunning={sessionRunning}/>
    {toast && <div className="toast" onClick={() => setToast(undefined)}>{toast}<X size={15}/></div>}
  </div>;
}

export default App;
