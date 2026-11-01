import { useEffect, useRef, useState } from "react";
import { ArrowDown, ChevronDown, ChevronRight, Gamepad2, LayoutGrid, List, Pencil, Play, Plus, Search, Square, Terminal, Trash2 } from "lucide-react";
import type { Game } from "../types";
import { LanguageFlag } from "../components/LanguageControls";
import { enginePresentation, isTestOnlyGame } from "../engines";

export type LibrarySortKey = "lastLaunch" | "addedAt" | "name";
export type LibrarySort = { key: LibrarySortKey; direction: "asc" | "desc" };
export type LibraryView = "list" | "grid";

const sortOptions: { value: LibrarySortKey; label: string }[] = [
  { value: "lastLaunch", label: "Última execução" },
  { value: "addedAt", label: "Data de adição" },
  { value: "name", label: "Nome" },
];

function LibraryDropdown<T extends string>({ label, value, options, onChange }: {
  label: string;
  value: T;
  options: { value: T; label: string }[];
  onChange: (value: T) => void;
}) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const closeOutside = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    const closeEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("pointerdown", closeOutside);
    document.addEventListener("keydown", closeEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOutside);
      document.removeEventListener("keydown", closeEscape);
    };
  }, [open]);
  return <div className="library-dropdown" ref={root}>
    <button type="button" className={`library-dropdown-trigger ${open ? "open" : ""}`} aria-label={label} aria-haspopup="listbox" aria-expanded={open} onClick={() => setOpen(!open)}>
      <span>{options.find(option => option.value === value)?.label ?? label}</span><ChevronDown size={15}/>
    </button>
    {open && <div className="library-dropdown-menu" role="listbox" aria-label={label}>
      {options.map(option => <button type="button" role="option" aria-selected={value === option.value} className={value === option.value ? "selected" : ""} key={option.value} onClick={() => { onChange(option.value); setOpen(false); }}>{option.label}</button>)}
    </div>}
  </div>;
}

type InstallState = "pending" | "installed" | "unavailable" | "unconfigured";

function installationState(game: Game, engineAvailable?: boolean): { kind: InstallState; label: string } {
  const detail = game.integrationStatus || "";
  if (engineAvailable === false) return { kind: "unavailable", label: "Motor indisponível" };
  if (/bloquead|incompatível|incompativel|parcial|ambígu|ambiguo/i.test(detail) || game.status === "Atenção") {
    return { kind: "unavailable", label: "Instalação bloqueada" };
  }
  if (game.status === "Em desenvolvimento") return { kind: "unavailable", label: "Jogo ainda não compatível" };
  if (!game.modelInstalled || !game.targetLanguage || game.status === "Novo" || game.status === "Modelo necessário") {
    return { kind: "unconfigured", label: "Não configurado" };
  }
  if (game.status === "Instalação pendente") return { kind: "pending", label: "Inicie para instalar" };
  return { kind: "installed", label: game.status === "Em teste" ? "Pronto para teste" : "Instalado" };
}

export function LibraryPage({ games, hasGames, engineNames, engineAvailability, filter, setFilter, sort, setSort, view, onViewChange, query, setQuery, onAddGame, onSelect, onLaunch, onStop, onDelete, activeGameId, onConsole }: {
  games: Game[];
  hasGames: boolean;
  engineNames: string[];
  engineAvailability: Record<string, boolean>;
  filter: string;
  setFilter: (value: string) => void;
  sort: LibrarySort;
  setSort: (value: LibrarySort) => void;
  view: LibraryView;
  onViewChange: (value: LibraryView) => void;
  query: string;
  setQuery: (value: string) => void;
  onAddGame: () => void;
  onSelect: (game: Game) => void;
  onLaunch: (game: Game) => void;
  onStop: () => void;
  onDelete: (game: Game) => void;
  activeGameId?: string;
  onConsole: () => void;
}) {
  const cardClickTimer = useRef<ReturnType<typeof setTimeout>>();
  useEffect(() => () => clearTimeout(cardClickTimer.current), []);
  const changeSortKey = (key: LibrarySortKey) => setSort({ key, direction: key === "name" ? "asc" : "desc" });
  const toggleSortDirection = () => setSort({ ...sort, direction: sort.direction === "asc" ? "desc" : "asc" });

  return <div className="page library-page">
    <h1 className="sr-only">Biblioteca</h1>
    <div className="library-header">
      <label className="search"><Search size={16}/><input value={query} onChange={event => setQuery(event.target.value)} placeholder="Buscar na biblioteca..."/></label>
      <div className="library-actions">
        <LibraryDropdown label="Filtrar por motor" value={filter} options={[{ value: "Todos", label: "Todos os motores" }, ...engineNames.map(name => ({ value: name, label: name }))]} onChange={setFilter}/>
        <div className="library-sort">
          <LibraryDropdown label="Ordenar biblioteca" value={sort.key} options={sortOptions} onChange={changeSortKey}/>
          <button type="button" className="sort-direction" onClick={toggleSortDirection} title={sort.key === "name" ? (sort.direction === "asc" ? "A–Z; inverter ordem" : "Z–A; inverter ordem") : (sort.direction === "desc" ? "Mais recentes primeiro; inverter ordem" : "Mais antigos primeiro; inverter ordem")} aria-label="Inverter ordem"><ArrowDown size={16} className={sort.direction === "asc" ? "ascending" : ""}/></button>
        </div>
        <button className="primary add-game-button" onClick={onAddGame}><Plus size={16}/>Adicionar jogo</button>
        <button className={`layout-switch ${view === "list" ? "active" : ""}`} onClick={() => onViewChange("list")} title="Visualização em lista" aria-label="Visualização em lista"><List size={18}/></button>
        <button className={`layout-switch ${view === "grid" ? "active" : ""}`} onClick={() => onViewChange("grid")} title="Visualização em grade" aria-label="Visualização em grade"><LayoutGrid size={18}/></button>
      </div>
    </div>
    {games.length === 0
      ? hasGames
        ? <section className="empty-card library-empty"><Search size={30}/><h2>Nenhum jogo encontrado</h2><p>Altere a busca ou escolha outro motor no filtro.</p></section>
        : <section className="empty-card library-empty"><div className="empty-art"><div/><Gamepad2 size={38}/></div><h2>Nenhum jogo na biblioteca</h2><p>Use “Adicionar jogo” acima para selecionar um executável e preparar a tradução.</p><div className="empty-steps"><div><b>1</b><span><strong>Selecione o jogo</strong><small>Escolha o executável principal.</small></span></div><div><b>2</b><span><strong>Defina o fluxo</strong><small>Use um modelo instalado ou baixe outro.</small></span></div><div><b>3</b><span><strong>Inicie e traduza</strong><small>Acompanhe tudo pelo console interno.</small></span></div></div></section>
      : <section className={`game-grid view-${view}`}>
          {games.map(game => {
            const isRunning = game.id === activeGameId;
            const install = installationState(game, engineAvailability[game.engine]);
            return <article className={`game-card install-${install.kind} ${isRunning ? "running" : ""}`} key={game.id} title={install.kind === "unavailable" ? game.integrationStatus : undefined} onClick={event => {
              if (isRunning && !(event.target as HTMLElement).closest("button")) {
                clearTimeout(cardClickTimer.current);
                cardClickTimer.current = setTimeout(onConsole, 350);
              }
            }} onDoubleClick={event => {
              if (!(event.target as HTMLElement).closest("button")) {
                clearTimeout(cardClickTimer.current);
                onSelect(game);
              }
            }}>
              <div className={`game-cover ${enginePresentation(game.engine).coverClass}`}>{game.iconData ? <img src={game.iconData} alt={`Ícone de ${game.name}`}/> : <Gamepad2 size={34}/>}</div>
              <div className="game-info">
                <div className="game-title"><div><h3>{game.name}</h3><span className="engine-tag">{game.engine}{game.engine === "RPG Maker" && ["95", "2000/2003", "XP", "VX", "VX Ace", "MV", "MZ", "Unite Mono", "Unite IL2CPP"].includes(game.runtime || "") ? ` · ${game.runtime} exp.` : ""}</span></div><p>{game.executablePath}</p></div>
                <div className="game-meta">
                  <div className="language-pair" title="Fluxo de tradução">{isTestOnlyGame(game) && !game.targetLanguage ? <span>Sem tradução</span> : game.flowMode === "chain" ? <><LanguageFlag code={game.sourceLanguage} name={game.sourceLanguage.toUpperCase()}/><ChevronRight size={12}/><LanguageFlag code="en" name="English"/><ChevronRight size={12}/><LanguageFlag code={game.targetLanguage} name={game.targetLanguage.toUpperCase()}/></> : (game.modelInstalled || isTestOnlyGame(game) && Boolean(game.targetLanguage)) ? <><LanguageFlag code={game.sourceLanguage} name={game.sourceLanguage.toUpperCase()}/><ChevronRight size={12}/><LanguageFlag code={game.targetLanguage} name={game.targetLanguage.toUpperCase()}/></> : <span>Sem modelo</span>}</div>
                  <div className="status"><i className={`dot ${isRunning ? "ok" : install.kind}`}/>{isRunning ? "EXECUTANDO" : install.label}</div>
                </div>
              </div>
              <time className="game-last-launch"><span>Última execução</span><b>{game.lastLaunch ? new Date(game.lastLaunch).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" }) : "Nunca iniciado"}</b></time>
              <div className="row-actions">{isRunning ? <><button className="play-action" onClick={onConsole} title="Abrir console" aria-label={`Abrir console de ${game.name}`}><Terminal size={17}/></button><button className="stop-action" onClick={onStop} title="Encerrar jogo" aria-label={`Encerrar ${game.name}`}><Square size={13} fill="currentColor"/></button></> : <button className="play-action" onClick={() => onLaunch(game)} title={isTestOnlyGame(game) ? "Abrir para teste, sem tradução" : game.engine === "RPG Maker" ? `Iniciar tradução ${game.runtime} experimental` : "Iniciar jogo"} aria-label={`Iniciar ${game.name}`}><Play size={17} fill="currentColor"/></button>}<button className="more-action" onClick={() => onSelect(game)} title="Editar jogo"><Pencil size={15}/></button><button className="model-delete" onClick={() => onDelete(game)} title="Remover jogo" aria-label={`Remover ${game.name}`}><Trash2 size={15}/></button></div>
            </article>;
          })}
        </section>}
  </div>;
}
