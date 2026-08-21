import { Fragment, useEffect, useMemo, useRef, useState, type MouseEvent as ReactMouseEvent } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { confirm, open } from "@tauri-apps/plugin-dialog";
import logo from "./assets/sftranslator-logo-v2.png";
import {
  Activity, Box, ChevronLeft, ChevronRight, CircleHelp, Download, Gamepad2,
  Languages, LayoutGrid, Library, List, Maximize2, Minus, Play, Plus, Search,
  Settings, Trash2, Wrench, X, Pencil
} from "lucide-react";
import type { EngineHealth, Game, TranslationModel } from "./types";

type DownloadTask = {id:string; modelId:string; name:string; status:"baixando"|"concluído"|"erro"; detail:string; progress:number};
type SessionLine = {kind:string; text:string};

const navigation = [
  ["Biblioteca", Library], ["Modelos", Box],
  ["Downloads", Download], ["Diagnósticos", Activity]
] as const;

const DEFAULT_SIDEBAR_WIDTH = 240;
const COMPACT_SIDEBAR_WIDTH = 68;
const MIN_SIDEBAR_WIDTH = 140;
const MAX_SIDEBAR_WIDTH = 260;

const LANGUAGE_FLAGS:Record<string,string>={
  ar:"🇸🇦",az:"🇦🇿",bg:"🇧🇬",bn:"🇧🇩",ca:"🇪🇸",cs:"🇨🇿",da:"🇩🇰",de:"🇩🇪",
  el:"🇬🇷",en:"🇺🇸",eo:"🌐",es:"🇪🇸",et:"🇪🇪",eu:"🇪🇸",fa:"🇮🇷",fi:"🇫🇮",
  fr:"🇫🇷",ga:"🇮🇪",gl:"🇪🇸",he:"🇮🇱",hi:"🇮🇳",hu:"🇭🇺",id:"🇮🇩",it:"🇮🇹",
  ja:"🇯🇵",ko:"🇰🇷",ky:"🇰🇬",lt:"🇱🇹",lv:"🇱🇻",ms:"🇲🇾",nb:"🇳🇴",nl:"🇳🇱",
  pb:"🇧🇷",pl:"🇵🇱",pt:"🇵🇹",ro:"🇷🇴",ru:"🇷🇺",sk:"🇸🇰",sl:"🇸🇮",sq:"🇦🇱",
  sv:"🇸🇪",sw:"🇰🇪",th:"🇹🇭",tl:"🇵🇭",tr:"🇹🇷",uk:"🇺🇦",ur:"🇵🇰",vi:"🇻🇳",
  zh:"🇨🇳",zt:"🇹🇼"
};
const languageFlag=(code:string)=>LANGUAGE_FLAGS[code.toLowerCase()]||"🌐";
const LOCAL_FLAG_STYLES:Record<string,string>={en:"us",pb:"br",pt:"pt",ja:"jp"};
function FlagSvg({flag}:{flag:string}) {
  if(flag==="us") return <svg viewBox="0 0 30 20" aria-hidden="true"><path fill="#fff" d="M0 0h30v20H0z"/><path fill="#b22234" d="M0 0h30v1.54H0zm0 3.08h30v1.54H0zm0 3.08h30v1.54H0zm0 3.08h30v1.54H0zm0 3.08h30v1.54H0zm0 3.08h30v1.54H0zm0 3.08h30v1.54H0z"/><path fill="#3c3b6e" d="M0 0h12v10.77H0z"/></svg>;
  if(flag==="br") return <svg viewBox="0 0 30 20" aria-hidden="true"><path fill="#009b3a" d="M0 0h30v20H0z"/><path fill="#ffdf00" d="m15 2 12 8-12 8L3 10z"/><circle cx="15" cy="10" r="4.5" fill="#002776"/><path d="M11 9.5c2.5-1.2 5.6-1 8 .4" fill="none" stroke="#fff" strokeWidth=".8"/></svg>;
  if(flag==="jp") return <svg viewBox="0 0 30 20" aria-hidden="true"><path fill="#fff" d="M0 0h30v20H0z"/><circle cx="15" cy="10" r="5.3" fill="#bc002d"/></svg>;
  return <svg viewBox="0 0 30 20" aria-hidden="true"><path fill="#046a38" d="M0 0h12v20H0z"/><path fill="#da291c" d="M12 0h18v20H12z"/><circle cx="12" cy="10" r="4" fill="none" stroke="#f5c542" strokeWidth="1.2"/></svg>;
}
function LanguageFlag({code,name}:{code:string;name:string}) {
  const style=LOCAL_FLAG_STYLES[code.toLowerCase()];
  return style
    ? <span className="flag-icon" role="img" aria-label={name} title={name}><FlagSvg flag={style}/></span>
    : <span className="flow-flag" role="img" aria-label={name} title={name}>{languageFlag(code)}</span>;
}

function App() {
  const [page, setPage] = useState("Biblioteca");
  const [games, setGames] = useState<Game[]>([]);
  const [health, setHealth] = useState<EngineHealth[]>([]);
  const [models, setModels] = useState<TranslationModel[]>([]);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("Todos");
  const [toast, setToast] = useState<string>();
  const [selectedGame, setSelectedGame] = useState<Game>();
  const [downloads, setDownloads] = useState<DownloadTask[]>([]);
  const [sessionGame, setSessionGame] = useState<Game>();
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
    setGames(await invoke<Game[]>("list_games"));
    setHealth(await invoke<EngineHealth[]>("engine_health"));
    setModels(await invoke<TranslationModel[]>("list_models"));
  };
  useEffect(() => {
    if (inTauri) refresh().catch(e => setToast(String(e)));
    else setHealth([
      { engine: "Ren'Py", sourceFound: true, runtimeFound: true, modelFound: true, details: "Hook moderno e legado; servidor local LibreTranslate/Argos." },
      { engine: "Unity", sourceFound: true, runtimeFound: true, modelFound: false, details: "Instalador BepInEx/XUnity para Mono e IL2CPP." }
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

  const addGame = async (): Promise<Game | undefined> => {
    const selected = await open({ multiple: false, filters: [{ name: "Executável do jogo", extensions: ["exe"] }] });
    if (!selected) return undefined;
    try {
      const game = await invoke<Game>("add_game", { executablePath: selected });
      await refresh();
      setToast(`${game.name} adicionado como ${game.engine}.`);
      return game;
    } catch (e) { setToast(String(e)); return undefined; }
  };

  const beginAddGame = async () => {
    setSelectedGame(undefined);
    const game = await addGame();
    if (!game) return;
    setSelectedGame(game);
    setPage("Adicionar jogo");
  };

  const configureGame = async (game: Game, sourceLanguage: string, targetLanguage: string) => {
    try {
      const requiredModel = models.find(model => model.fromCode === sourceLanguage && model.toCode === targetLanguage);
      if (requiredModel && !requiredModel.installed && !await downloadModel(requiredModel)) return;
      const updated = await invoke<Game>("configure_game", { gameId: game.id, sourceLanguage, targetLanguage });
      await refresh(); setSelectedGame(updated); setPage("Biblioteca");
      setToast(updated.modelInstalled ? "Configuração salva. O fluxo está disponível." : "Configuração salva. Baixe o fluxo necessário em Modelos.");
    } catch (e) { setToast(String(e)); }
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
    setSessionGame(game); setSessionLines([]); setSessionRunning(true); setPage("Sessão");
    try { await invoke("launch_game", { gameId: game.id }); await refresh(); }
    catch (e) { setSessionRunning(false); setSessionLines([{kind:"error",text:String(e)}]); }
  };

  const removeGame = async (game: Game) => {
    if (!await confirm(`Os arquivos do jogo não serão apagados.`, { title: `Remover “${game.name}”?`, kind: "warning" })) return;
    try {
      await invoke("remove_game", { gameId: game.id });
      setSelectedGame(undefined);
      await refresh();
      setToast(`${game.name} foi removido da biblioteca.`);
    } catch (e) { setToast(String(e)); }
  };

  const filtered = useMemo(() => games.filter(game => {
    const matchesFilter = filter === "Todos" || game.engine === filter;
    return matchesFilter && game.name.toLowerCase().includes(query.toLowerCase());
  }), [games, query, filter]);

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
          : page === "Sessão"
            ? sessionRunning ? "Preparação do motor, servidor local e tradução em execução." : "Sessão encerrada; o histórico permanece disponível."
            : "SFTranslator monitora os componentes locais dos dois motores.";

  return <div className="shell">
    <header className="titlebar" data-tauri-drag-region onMouseDown={event => { if (event.button === 0 && !(event.target as HTMLElement).closest("button")) appWindow?.startDragging(); }} onDoubleClick={event => { if (!(event.target as HTMLElement).closest("button")) appWindow?.toggleMaximize(); }}>
      <div className="titlebar-engines">{["Ren'Py", "Unity"].map(engine => { const item=health.find(value=>value.engine===engine); const online=Boolean(item?.sourceFound&&item?.runtimeFound); return <span key={engine}><i className={`dot ${online?"ok":""}`}/>{engine}</span>; })}</div>
      <div className="app-title" data-tauri-drag-region><strong>SFTranslator</strong><span>v0.1.0</span></div>
      <div className="window-actions">
        <button onClick={() => appWindow?.minimize()} aria-label="Minimizar"><Minus size={16}/></button>
        <button onClick={() => appWindow?.toggleMaximize()} aria-label="Maximizar"><Maximize2 size={14}/></button>
        <button className="close" onClick={() => appWindow?.close()} aria-label="Fechar"><X size={17}/></button>
      </div>
    </header>
    <div className={`workspace ${isResizingSidebar ? "workspace-resizing" : ""}`}>
      <aside ref={sidebarRef} className={isSidebarCompact ? "sidebar-compact" : ""} style={{ width: sidebarWidth }}>
        <div className="sidebar-brand"><img src={logo} alt="SFTranslator"/></div>
        <nav>{navigation.map(([label, Icon],index) => <Fragment key={label}>{index===0&&<span className="nav-group-label">Biblioteca</span>}{index===1&&<span className="nav-group-label">Ferramentas</span>}<button title={isSidebarCompact ? label : undefined} className={page === label ? "active" : ""} onClick={() => setPage(label)}><Icon size={18}/><span>{label}</span>{label === "Biblioteca" && <b className="nav-count">{games.length}</b>}</button></Fragment>)}</nav>
        <section className="sidebar-overview"><span>VISÃO GERAL</span><div><button onClick={()=>setPage("Biblioteca")}><b>{games.length}</b><small>{games.length===1?"Jogo":"Jogos"}</small></button><button onClick={()=>setPage("Modelos")}><b>{installedModelCount}</b><small>{installedModelCount===1?"Modelo":"Modelos"}</small></button></div><p><i className={`dot ${sessionRunning?"ok":""}`}/>{sessionRunning?"Tradução em andamento":"Aplicativo pronto"}</p></section>
        <div className="sidebar-footer"><button className={page === "Configurações" ? "active" : ""} title="Configurações" onClick={() => setPage("Configurações")}><Settings size={18}/></button><button className={page === "Sobre" ? "active" : ""} title="Sobre" onClick={() => setPage("Sobre")}><CircleHelp size={18}/></button></div>
        <div className="sidebar-resizer" role="separator" aria-label="Redimensionar barra lateral" aria-orientation="vertical" onMouseDown={startSidebarResize} onDoubleClick={toggleSidebarWidth}/>
      </aside>
      <main>
        {page === "Biblioteca" && (selectedGame
          ? <GameDetails game={selectedGame} models={models} onBack={() => setSelectedGame(undefined)} onRemove={() => removeGame(selectedGame)} onSave={configureGame}/>
          : <LibraryPage games={filtered} filter={filter} setFilter={setFilter} query={query} setQuery={setQuery} onAddGame={beginAddGame} onSelect={setSelectedGame} onLaunch={launchGame}/>)} 
        {page === "Adicionar jogo" && <Wizard existingGame={selectedGame} models={models} onSave={configureGame}/>} 
        {page === "Modelos" && <Models models={models} games={games} onOpenGame={openGameDetails} onDelete={deleteModel} onDownload={downloadModel}/>} 
        {page === "Downloads" && <DownloadsPage tasks={downloads}/>} 
        {page === "Sessão" && sessionGame && <SessionPage game={sessionGame} lines={sessionLines} running={sessionRunning} onBack={() => setPage("Biblioteca")}/>} 
        {page === "Diagnósticos" && <Diagnostics health={health}/>} 
        {page === "Configurações" && <SettingsPage/>}
        {page === "Sobre" && <EmptyPage icon={Languages} title="SFTranslator" text="Uma biblioteca universal de tradução para jogos Ren'Py e Unity."/>}
        <footer className="context-bar"><span><Activity size={14}/>{contextText}</span><b>{sessionRunning ? "Sessão ativa" : "Pronto"}</b></footer>
      </main>
    </div>
    {toast && <div className="toast" onClick={() => setToast(undefined)}>{toast}<X size={15}/></div>}
  </div>;
}

function PageHeading({ eyebrow, title, text, action }: { eyebrow?: string; title: string; text: string; action?: React.ReactNode }) {
  return <div className="page-heading"><div>{eyebrow && <span className="eyebrow">{eyebrow}</span>}<h1>{title}</h1><p>{text}</p></div>{action}</div>;
}

function LibraryPage({ games, filter, setFilter, query, setQuery, onAddGame, onSelect, onLaunch }: { games: Game[]; filter: string; setFilter: (v:string)=>void; query:string; setQuery:(v:string)=>void; onAddGame:()=>void; onSelect:(game:Game)=>void; onLaunch:(game:Game)=>void }) {
  const [view,setView]=useState<"list"|"grid">(()=>{try{return localStorage.getItem("sftranslator_library_view")==="grid"?"grid":"list";}catch{return "list";}});
  const changeView=(next:"list"|"grid")=>{setView(next);try{localStorage.setItem("sftranslator_library_view",next);}catch{/* noop */}};
  return <div className="page library-page">
    <h1 className="sr-only">Biblioteca</h1>
    <div className="library-header"><label className="search"><Search size={16}/><input value={query} onChange={e=>setQuery(e.target.value)} placeholder="Buscar na biblioteca..."/></label><div className="library-actions"><div className="segments">{["Todos","Ren'Py","Unity"].map(item=><button className={filter===item?"selected":""} onClick={()=>setFilter(item)} key={item}>{item}</button>)}</div><button className="primary add-game-button" onClick={onAddGame}><Plus size={16}/>Adicionar jogo</button><button className={`layout-switch ${view==="list"?"active":""}`} onClick={()=>changeView("list")} title="Visualização em lista" aria-label="Visualização em lista"><List size={18}/></button><button className={`layout-switch ${view==="grid"?"active":""}`} onClick={()=>changeView("grid")} title="Visualização em grade" aria-label="Visualização em grade"><LayoutGrid size={18}/></button></div></div>
    {games.length === 0
      ? <section className="empty-card library-empty"><div className="empty-art"><div/><Gamepad2 size={38}/></div><h2>Nenhum jogo na biblioteca</h2><p>Use “Adicionar jogo” acima para selecionar um executável e preparar a tradução.</p><div className="empty-steps"><div><b>1</b><span><strong>Selecione o jogo</strong><small>Escolha o executável principal.</small></span></div><div><b>2</b><span><strong>Defina o fluxo</strong><small>Use um modelo instalado ou baixe outro.</small></span></div><div><b>3</b><span><strong>Inicie e traduza</strong><small>Acompanhe tudo pelo console interno.</small></span></div></div></section>
      : <section className={`game-grid view-${view}`}>
          {games.map(game=><article className={`game-card ${game.status === "Pronto" ? "ready" : "pending"}`} key={game.id}>
            <div className={`game-cover ${game.engine === "Unity" ? "unity" : "renpy"}`}>{game.iconData ? <img src={game.iconData} alt={`Ícone de ${game.name}`}/> : <Gamepad2 size={34}/>}</div>
            <div className="game-info">
              <div className="game-title"><div><h3>{game.name}</h3><span className="engine-tag">{game.engine}</span></div><p>{game.executablePath}</p></div>
              <div className="game-meta">
                <div className="language-pair" title="Fluxo de tradução">{game.modelInstalled?<><span>{game.sourceLanguage.toUpperCase()}</span><ChevronRight size={12}/><span>{game.targetLanguage.toUpperCase()}</span></>:<span>Sem modelo</span>}</div>
                <div className="status"><i className={`dot ${game.status === "Pronto" ? "ok" : "warn"}`}/>{game.status}</div>
              </div>
            </div>
            <time className="game-last-launch"><span>Última execução</span><b>{game.lastLaunch?new Date(game.lastLaunch).toLocaleString("pt-BR",{dateStyle:"short",timeStyle:"short"}):"Nunca iniciado"}</b></time>
            <div className="row-actions"><button className="play-action" onClick={()=>onLaunch(game)} title="Iniciar jogo"><Play size={17} fill="currentColor"/></button><button className="more-action" onClick={()=>onSelect(game)} title="Editar jogo"><Pencil size={15}/></button></div>
          </article>)}
        </section>}
  </div>;
}

function GameDetails({ game, models, onBack, onRemove, onSave }: { game: Game; models:TranslationModel[]; onBack:()=>void; onRemove:()=>void; onSave:(game:Game,source:string,target:string)=>Promise<void> }) {
  const sources=useMemo(()=>Array.from(new Map(models.map(model=>[model.fromCode,{code:model.fromCode,name:model.fromName}])).values()).sort((a,b)=>a.name.localeCompare(b.name)),[models]);
  const preferredSource=game.sourceLanguage||game.detectedLanguage||sources[0]?.code||"";
  const [source,setSource]=useState(sources.some(item=>item.code===preferredSource)?preferredSource:(game.detectedLanguage||sources[0]?.code||""));
  const destinations=useMemo(()=>models.filter(model=>model.fromCode===source).sort((a,b)=>a.toName.localeCompare(b.toName)),[models,source]);
  const [target,setTarget]=useState(game.targetLanguage||destinations[0]?.toCode||"");
  const [saving,setSaving]=useState(false);
  const installedModels=useMemo(()=>models.filter(model=>model.installed).sort((a,b)=>`${a.fromName}${a.toName}`.localeCompare(`${b.fromName}${b.toName}`)),[models]);
  useEffect(()=>{const next=game.sourceLanguage||game.detectedLanguage||sources[0]?.code||"";setSource(sources.some(item=>item.code===next)?next:(game.detectedLanguage||sources[0]?.code||""));setTarget(game.targetLanguage||"");},[game.id]);
  useEffect(()=>{if(!destinations.some(model=>model.toCode===target))setTarget(destinations[0]?.toCode||"");},[source,models]);
  const selectedModel=models.find(model=>model.fromCode===source&&model.toCode===target);
  const save=async()=>{if(!selectedModel)return;setSaving(true);try{await onSave(game,source,target);}finally{setSaving(false);}};
  const pathParts=game.executablePath.split(/[\\/]/);
  const executableName=pathParts.pop()||game.name;
  const gameDirectory=pathParts.join("\\");
  return <div className="page game-config-page">
    <header className="game-config-header"><button className="back-button" onClick={onBack}><ChevronLeft size={16}/>Biblioteca</button><span>Configuração completa do jogo</span></header>
    <section className="game-config-identity">
      <div className="game-identity-primary"><div className={`details-icon game-cover ${game.engine === "Unity"?"unity":"renpy"}`}>{game.iconData?<img src={game.iconData} alt=""/>:<Gamepad2 size={38}/>}</div><div><span className="eyebrow">{game.engine.toUpperCase()}</span><h1>{game.name}</h1><p>{game.runtime||game.engine}{game.architecture?` · ${game.architecture}`:""} · <b>{game.status}</b></p></div></div>
      <div className="game-summary-strip"><div><span>Idioma detectado</span><b>{(game.detectedLanguage||"?").toUpperCase()} <small>{Math.round((game.languageConfidence||0)*100)}%</small></b></div><div><span>Fluxo selecionado</span><b>{source.toUpperCase()||"—"} <i>→</i> {target.toUpperCase()||"—"}</b></div><div><span>Modelo universal</span><b className={selectedModel?.installed?"summary-ready":""}>{selectedModel?.installed?"Instalado":"Necessário"}</b></div></div>
      <button className="primary" disabled={!selectedModel||saving} onClick={save}><Pencil size={15}/>{saving?"Salvando…":"Salvar configuração"}</button>
    </section>
    <section className="game-config-panel">
      <div className="game-file-card"><span>EXECUTÁVEL DO JOGO</span><strong>{executableName}</strong><code title={game.executablePath}>{gameDirectory}</code><div className="game-file-facts"><div><span>Motor</span><b>{game.engine}</b></div><div><span>Runtime</span><b>{game.runtime||"Padrão"}</b></div><div><span>Arquitetura</span><b>{game.architecture||"Automática"}</b></div><div><span>Estado</span><b>{game.status}</b></div></div><div className="game-integration-row"><span>Integração instalada no jogo</span><b>{game.integrationStatus||"Será verificada ao iniciar"}</b></div></div>
      <div className="game-flow-editor"><div className="editor-title"><div><span>TRADUÇÃO</span><h2>Configuração do jogo</h2></div><span className={`pill ${game.modelInstalled?"success":"neutral"}`}>{game.modelInstalled?"Modelo instalado":"Modelo necessário"}</span></div><div className="detected-language"><Languages size={18}/><div><b>Idioma detectado: {(game.detectedLanguage||"?").toUpperCase()}</b><span>{Math.round((game.languageConfidence||0)*100)}% de confiança na análise</span></div></div><div className="form-row"><label>Idioma original<select value={source} onChange={event=>setSource(event.target.value)}>{sources.map(item=><option key={item.code} value={item.code}>{item.name}</option>)}</select></label><label>Destino disponível<select value={target} onChange={event=>setTarget(event.target.value)}>{destinations.map(model=><option key={model.id} value={model.toCode}>{model.toName}</option>)}</select></label></div>{installedModels.length>0&&<div className="installed-flow-picker compact"><div><b>Modelos instalados</b><span>Selecione um par pronto.</span></div><div className="installed-flow-list">{installedModels.map(model=><button key={model.id} className={source===model.fromCode&&target===model.toCode?"selected":""} onClick={()=>{setSource(model.fromCode);setTarget(model.toCode);}}><span>{model.fromCode.toUpperCase()}</span><ChevronRight size={12}/><span>{model.toCode.toUpperCase()}</span><small className="flow-flags" aria-label={`${model.fromName} para ${model.toName}`}><LanguageFlag code={model.fromCode} name={model.fromName}/><ChevronRight size={10}/><LanguageFlag code={model.toCode} name={model.toName}/></small></button>)}</div></div>}<div className="flow-result"><span>{source.toUpperCase()} → {target.toUpperCase()}</span><b>{selectedModel?.installed?"Pronto para usar":selectedModel?"Será baixado ao salvar":"Fluxo indisponível"}</b></div></div>
    </section>
    <footer className="game-config-danger"><div><h3>Remover jogo</h3><p>Remove somente o cadastro do SFTranslator.</p></div><div className="danger-facts"><span>Arquivos preservados</span><span>Modelo preservado</span></div><button className="danger-button" onClick={onRemove}><Trash2 size={16}/>Remover da biblioteca</button></footer>
  </div>;
}

function Wizard({ existingGame: game, models, onSave }: { existingGame?:Game; models:TranslationModel[]; onSave:(game:Game,source:string,target:string)=>void }) {
  const sources=useMemo(()=>Array.from(new Map(models.map(model=>[model.fromCode,{code:model.fromCode,name:model.fromName}])).values()).sort((a,b)=>a.name.localeCompare(b.name)),[models]);
  const installedModels=useMemo(()=>models.filter(model=>model.installed).sort((a,b)=>`${a.fromName}${a.toName}`.localeCompare(`${b.fromName}${b.toName}`)),[models]);
  const detected=game?.detectedLanguage || game?.sourceLanguage || "";
  const initialSource=sources.some(item=>item.code===detected)?detected:(sources[0]?.code||"");
  const [source,setSource]=useState(initialSource);
  const destinations=useMemo(()=>models.filter(model=>model.fromCode===source).sort((a,b)=>a.toName.localeCompare(b.toName)),[models,source]);
  const [target,setTarget]=useState(game?.targetLanguage || "");
  useEffect(()=>{if(!destinations.some(model=>model.toCode===target))setTarget(destinations[0]?.toCode||"");},[source,models]);
  const selectedModel=models.find(model=>model.fromCode===source&&model.toCode===target);
  if (!game) return null;
  return <div className="page wizard-page"><section className="wizard-card wizard-card-fit">
    <div className="step done"><b>1</b><span>Jogo identificado</span></div>
    <div className="step active"><b>2</b><span>Escolher fluxo</span></div>
    <div className="step"><b>3</b><span>Instalar ao iniciar</span></div>
    <div className="wizard-analysis">
      <div className="analysis-head"><div className={`game-cover ${game.engine === "Unity"?"unity":"renpy"}`}>{game.iconData?<img src={game.iconData} alt=""/>:<Gamepad2/>}</div><div><span className="pill neutral">{game.engine}</span><h2>{game.name}</h2><p>{game.runtime} · {game.architecture} · {game.integrationStatus}</p></div></div>
      <div className="confidence"><Languages size={20}/><div><b>Idioma detectado: {(game.detectedLanguage||"?").toUpperCase()}</b><span>Confiabilidade da análise</span></div><strong>{Math.round((game.languageConfidence||0)*100)}%</strong></div>
      <div className="form-row"><label>Idioma original<select value={source} onChange={e=>setSource(e.target.value)}>{sources.map(item=><option key={item.code} value={item.code}>{item.name}</option>)}</select></label><label>Fluxos disponíveis a partir de {sources.find(item=>item.code===source)?.name||source}<select value={target} onChange={e=>setTarget(e.target.value)}>{destinations.map(model=><option key={model.id} value={model.toCode}>{model.toName}</option>)}</select></label></div>
      {installedModels.length>0&&<div className="installed-flow-picker"><div><b>Modelos já instalados</b><span>Selecione um par para preencher os dois idiomas.</span></div><div className="installed-flow-list">{installedModels.map(model=><button key={model.id} className={source===model.fromCode&&target===model.toCode?"selected":""} onClick={()=>{setSource(model.fromCode);setTarget(model.toCode);}}><span>{model.fromCode.toUpperCase()}</span><ChevronRight size={12}/><span>{model.toCode.toUpperCase()}</span><small className="flow-flags" aria-label={`${model.fromName} para ${model.toName}`}><LanguageFlag code={model.fromCode} name={model.fromName}/><ChevronRight size={10}/><LanguageFlag code={model.toCode} name={model.toName}/></small></button>)}</div></div>}
      <div className="flow-result"><span>{source.toUpperCase()} → {target.toUpperCase()}</span><b>{selectedModel?.installed?"Modelo instalado":selectedModel?"Disponível para baixar":"Fluxo indisponível"}</b></div>
      <button className="primary wizard-next" disabled={!selectedModel} onClick={()=>selectedModel&&onSave(game,source,target)}>Salvar e continuar<ChevronRight size={16}/></button>
    </div>
  </section></div>;
}

function Models({ models, games, onOpenGame, onDelete, onDownload }: { models: TranslationModel[]; games:Game[]; onOpenGame:(game:Game)=>void; onDelete:(model:TranslationModel)=>void; onDownload:(model:TranslationModel)=>Promise<boolean> }) {
  const [showCatalog,setShowCatalog]=useState(false);
  const available=models.filter(model=>!model.installed);
  const installed=models.filter(model=>model.installed);
  const sources=Array.from(new Map(available.map(model=>[model.fromCode,{code:model.fromCode,name:model.fromName}])).values()).sort((a,b)=>a.name.localeCompare(b.name));
  const [source,setSource]=useState("");
  const destinations=available.filter(model=>model.fromCode===source).sort((a,b)=>a.toName.localeCompare(b.toName));
  const [selectedId,setSelectedId]=useState("");
  useEffect(()=>{if(showCatalog&&!sources.some(item=>item.code===source))setSource(sources[0]?.code||"");},[showCatalog,models]);
  useEffect(()=>{if(!destinations.some(model=>model.id===selectedId))setSelectedId(destinations[0]?.id||"");},[source,models]);
  const selected=models.find(model=>model.id===selectedId);
  const install=async()=>{if(selected){await onDownload(selected);setShowCatalog(false);}};
  const configuredGames=games.filter(game=>game.modelInstalled).length;
  return <div className="page models-page"><PageHeading eyebrow="FLUXOS ARGOS" title="Modelos universais" text="Fluxos instalados e compartilhados por Unity e Ren'Py." action={<button className="primary" onClick={()=>setShowCatalog(true)}><Download size={16}/>Baixar modelo</button>}/><div className="universal-note"><Languages size={19}/><div><b>Os modelos são pares direcionados</b><span>A disponibilidade é definida pelo catálogo Argos: ter japonês como origem não significa que todos os destinos existem.</span></div></div><section className="models-overview"><article><Box size={20}/><div><span>Instalados</span><b>{installed.length}</b><small>fluxos universais prontos</small></div></article><article><Gamepad2 size={20}/><div><span>Jogos configurados</span><b>{configuredGames}</b><small>usando modelos locais</small></div></article><article><Download size={20}/><div><span>No catálogo</span><b>{available.length}</b><small>fluxos disponíveis para baixar</small></div></article></section><section className="model-grid">{installed.length ? installed.map(model=>{const modelGames=games.filter(game=>game.modelInstalled&&game.sourceLanguage===model.fromCode&&game.targetLanguage===model.toCode);return <article key={model.id} className="installed"><header className="model-card-head"><div className="model-flag-flow"><LanguageFlag code={model.fromCode} name={model.fromName}/><ChevronRight size={16}/><LanguageFlag code={model.toCode} name={model.toName}/></div><span className="pill success">Instalado</span></header><div className="model-card-copy"><h3>{model.fromName} → {model.toName}</h3><p>Fluxo offline do Argos Translate, compartilhado entre os dois motores.</p></div><div className="model-stat-grid"><div><span>Versão</span><b>{model.version}</b></div><div><span>Compatibilidade</span><b>Unity + Ren'Py</b></div></div><footer><div className="model-usage">{modelGames.length>0&&<div className="model-game-icons">{modelGames.map(game=><button key={game.id} onClick={()=>onOpenGame(game)} title={`Abrir ${game.name}`}>{game.iconData?<img src={game.iconData} alt=""/>:<Gamepad2 size={14}/>}</button>)}</div>}<small>{modelGames.length ? `${modelGames.length} ${modelGames.length===1?"jogo usando":"jogos usando"}` : "Disponível para todos os jogos"}</small></div><button className="model-delete" onClick={()=>onDelete(model)} title="Apagar modelo"><Trash2 size={14}/></button></footer></article>}) : <div className="no-models"><Box size={25}/><h3>Nenhum modelo instalado</h3><p>Use “Baixar modelo” acima para escolher um fluxo disponível.</p></div>}</section><section className="models-guide"><article><Languages size={19}/><div><b>Uso universal</b><span>Um único fluxo instalado atende jogos Unity e Ren'Py.</span></div></article><article><Wrench size={19}/><div><b>Configuração por jogo</b><span>Escolha o par de idiomas na edição do jogo.</span></div></article><article><Activity size={19}/><div><b>Tradução local</b><span>Os fluxos funcionam pelo runtime local do SFTranslator.</span></div></article></section>{showCatalog&&<div className="modal-backdrop" onMouseDown={event=>{if(event.target===event.currentTarget)setShowCatalog(false)}}><section className="model-modal"><header><div><span className="eyebrow">CATÁLOGO ARGOS</span><h2>Baixar modelo</h2><p>Escolha uma origem; o destino exibirá somente pares existentes.</p></div><button onClick={()=>setShowCatalog(false)}><X size={18}/></button></header>{available.length?<><div className="form-row"><label>Idioma original<select value={source} onChange={event=>setSource(event.target.value)}>{sources.map(item=><option key={item.code} value={item.code}>{item.name}</option>)}</select></label><label>Destino disponível<select value={selectedId} onChange={event=>setSelectedId(event.target.value)}>{destinations.map(model=><option key={model.id} value={model.id}>{model.toName}</option>)}</select></label></div>{selected&&<div className="catalog-selection"><div className="flow"><span>{selected.fromCode.toUpperCase()}</span><ChevronRight/><span>{selected.toCode.toUpperCase()}</span></div><div><b>{selected.fromName} → {selected.toName}</b><small>Argos Translate · versão {selected.version}</small></div></div>}<footer><button className="secondary" onClick={()=>setShowCatalog(false)}>Cancelar</button><button className="primary" disabled={!selected} onClick={install}><Download size={16}/>Baixar e instalar</button></footer></>:<div className="no-models"><Box/><h3>Todos os fluxos estão instalados</h3></div>}</section></div>}</div>;
}

function Diagnostics({ health }: { health: EngineHealth[] }) { return <div className="page"><PageHeading eyebrow="SAÚDE DO SISTEMA" title="Diagnósticos" text="Uma leitura honesta dos componentes legados encontrados nesta instalação."/><section className="diagnostic-grid">{health.map(h=><article key={h.engine}><div className="diag-head"><div className="panel-icon"><Wrench size={20}/></div><div><h3>Motor {h.engine}</h3><p>{h.details}</p></div></div><Check label="Código-fonte" value={h.sourceFound}/><Check label="Runtime empacotado" value={h.runtimeFound}/><Check label="Modelo offline" value={h.modelFound}/></article>)}</section></div>; }
function Check({label,value}:{label:string;value:boolean}) { return <div className="check"><span>{label}</span><b className={value?"good":"muted"}>{value?"Encontrado":"Não confirmado"}</b></div>; }
function SettingsPage() { return <div className="page"><PageHeading eyebrow="PREFERÊNCIAS" title="Configurações" text="A nova base manterá modelos e dados fora das pastas dos jogos."/><section className="settings-card"><div><h3>Tema</h3><p>Interface escura</p><span className="switch on"><i/></span></div><div><h3>Idioma da interface</h3><p>Português (Brasil)</p><button className="secondary">Alterar</button></div><div><h3>Modo avançado</h3><p>Exibe runtime, arquitetura e logs técnicos</p><span className="switch"><i/></span></div></section></div>; }
function DownloadsPage({tasks}:{tasks:DownloadTask[]}) { return <div className="page"><PageHeading eyebrow="OPERAÇÕES" title="Downloads" text="Acompanhe modelos e componentes sem bloquear o restante do aplicativo."/>{tasks.length?<section className="downloads-list">{tasks.map(task=><article key={task.id} className={task.status}><div className="download-status">{task.status==="baixando"?<span className="spinner"/>:task.status==="concluído"?<Activity size={19}/>:<X size={19}/>}</div><div className="download-copy"><h3>{task.name}</h3><p>{task.detail}</p>{task.status==="baixando"&&<div className="progress-track"><i style={{width:`${task.progress}%`}}/></div>}</div><span className="download-label">{task.status}</span></article>)}</section>:<section className="empty-card compact"><div className="panel-icon"><Download size={24}/></div><h2>Nenhum download por enquanto</h2><p>Os modelos iniciados em Modelos Universais aparecerão aqui.</p></section>}</div>; }
function SessionPage({game,lines,running,onBack}:{game:Game;lines:SessionLine[];running:boolean;onBack:()=>void}) {
  const outputRef=useRef<HTMLDivElement>(null);
  const followOutput=useRef(true);

  useEffect(()=>{
    followOutput.current=true;
    const output=outputRef.current;
    if(output) output.scrollTop=output.scrollHeight;
  },[game.id]);

  useEffect(()=>{
    if(!followOutput.current)return;
    const frame=requestAnimationFrame(()=>{
      const output=outputRef.current;
      if(output) output.scrollTop=output.scrollHeight;
    });
    return()=>cancelAnimationFrame(frame);
  },[lines.length]);

  const updateScrollFollow=()=>{
    const output=outputRef.current;
    if(!output)return;
    followOutput.current=output.scrollHeight-output.scrollTop-output.clientHeight<=24;
  };

  return <div className="session-page">
    <header><button className="back-button" onClick={onBack}><ChevronLeft size={15}/>Biblioteca</button><div><span className={`session-dot ${running?"live":""}`}/><b>{game.name}</b><small>{running?"tradução em tempo real":"jogo encerrado"}</small></div></header>
    <section className="terminal">
      <div className="terminal-head"><span>SFTranslator runtime</span><span>{game.sourceLanguage.toUpperCase()} → {game.targetLanguage.toUpperCase()}</span></div>
      <div className="terminal-output" ref={outputRef} onScroll={updateScrollFollow}>{lines.length?lines.map((line,index)=><p key={index} className={line.kind}><i>{line.kind==="error"?"!":line.kind==="system"?"›":"·"}</i>{line.text}</p>):<p className="system"><i>›</i>Aguardando saída do motor de tradução…</p>}</div>
      <footer><span>Saída do tradutor</span><b>{running?"acompanhando":"finalizada"}</b></footer>
    </section>
  </div>;
}
function EmptyPage({icon:Icon,title,text}:{icon:typeof Download;title:string;text:string}) { return <div className="page"><PageHeading title={title} text={text}/><section className="empty-card compact"><div className="panel-icon"><Icon size={24}/></div><h2>Nenhuma atividade por enquanto</h2><p>Esta área será ativada durante a migração dos fluxos de instalação.</p></section></div>; }

export default App;
