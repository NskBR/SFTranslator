import { useEffect, useRef, useState } from "react";
import { ChevronRight, Gamepad2, LayoutGrid, List, Pencil, Play, Plus, Search, Square, Terminal, Trash2 } from "lucide-react";
import type { Game } from "../types";
import { LanguageFlag } from "../components/LanguageControls";
import { enginePresentation, isTestOnlyGame } from "../engines";

export function LibraryPage({ games, engineNames, filter, setFilter, query, setQuery, onAddGame, onSelect, onLaunch, onStop, onDelete, activeGameId, onConsole }: { games: Game[]; engineNames:string[]; filter: string; setFilter: (v:string)=>void; query:string; setQuery:(v:string)=>void; onAddGame:()=>void; onSelect:(game:Game)=>void; onLaunch:(game:Game)=>void; onStop:()=>void; onDelete:(game:Game)=>void; activeGameId?:string; onConsole:()=>void }) {
  const cardClickTimer = useRef<ReturnType<typeof setTimeout>>();
  useEffect(() => () => clearTimeout(cardClickTimer.current), []);
  const [view,setView]=useState<"list"|"grid">(()=>{try{return localStorage.getItem("sftranslator_library_view")==="grid"?"grid":"list";}catch{return "list";}});
  const changeView=(next:"list"|"grid")=>{setView(next);try{localStorage.setItem("sftranslator_library_view",next);}catch{/* noop */}};
  return <div className="page library-page">
    <h1 className="sr-only">Biblioteca</h1>
    <div className="library-header"><label className="search"><Search size={16}/><input value={query} onChange={e=>setQuery(e.target.value)} placeholder="Buscar na biblioteca..."/></label><div className="library-actions"><div className="segments">{["Todos",...engineNames].map(item=><button className={filter===item?"selected":""} onClick={()=>setFilter(item)} key={item}>{item}</button>)}</div><button className="primary add-game-button" onClick={onAddGame}><Plus size={16}/>Adicionar jogo</button><button className={`layout-switch ${view==="list"?"active":""}`} onClick={()=>changeView("list")} title="Visualização em lista" aria-label="Visualização em lista"><List size={18}/></button><button className={`layout-switch ${view==="grid"?"active":""}`} onClick={()=>changeView("grid")} title="Visualização em grade" aria-label="Visualização em grade"><LayoutGrid size={18}/></button></div></div>
    {games.length === 0
      ? <section className="empty-card library-empty"><div className="empty-art"><div/><Gamepad2 size={38}/></div><h2>Nenhum jogo na biblioteca</h2><p>Use “Adicionar jogo” acima para selecionar um executável e preparar a tradução.</p><div className="empty-steps"><div><b>1</b><span><strong>Selecione o jogo</strong><small>Escolha o executável principal.</small></span></div><div><b>2</b><span><strong>Defina o fluxo</strong><small>Use um modelo instalado ou baixe outro.</small></span></div><div><b>3</b><span><strong>Inicie e traduza</strong><small>Acompanhe tudo pelo console interno.</small></span></div></div></section>
      : <section className={`game-grid view-${view}`}>
          {games.map(game=>{const isRunning=game.id===activeGameId;const visibleStatus=isRunning?"EXECUTANDO":game.status;return <article className={`game-card ${isRunning?"running":""}`} key={game.id} onClick={event=>{if(isRunning && !(event.target as HTMLElement).closest("button")){clearTimeout(cardClickTimer.current);cardClickTimer.current=setTimeout(onConsole,350);}}} onDoubleClick={event=>{if(!(event.target as HTMLElement).closest("button")){clearTimeout(cardClickTimer.current);onSelect(game);}}}>
            <div className={`game-cover ${enginePresentation(game.engine).coverClass}`}>{game.iconData ? <img src={game.iconData} alt={`Ícone de ${game.name}`}/> : <Gamepad2 size={34}/>}</div>
            <div className="game-info">
              <div className="game-title"><div><h3>{game.name}</h3><span className="engine-tag">{game.engine}{game.engine==="RPG Maker"&&["MV","MZ","Unite Mono","Unite IL2CPP"].includes(game.runtime||"")?` · ${game.runtime} exp.`:""}</span></div><p>{game.executablePath}</p></div>
              <div className="game-meta">
                <div className="language-pair" title="Fluxo de tradução">{isTestOnlyGame(game)&&!game.targetLanguage?<span>Sem tradução</span>:game.flowMode==="chain"?<><LanguageFlag code={game.sourceLanguage} name={game.sourceLanguage.toUpperCase()}/><ChevronRight size={12}/><LanguageFlag code="en" name="English"/><ChevronRight size={12}/><LanguageFlag code={game.targetLanguage} name={game.targetLanguage.toUpperCase()}/></>:(game.modelInstalled||isTestOnlyGame(game)&&Boolean(game.targetLanguage))?<><LanguageFlag code={game.sourceLanguage} name={game.sourceLanguage.toUpperCase()}/><ChevronRight size={12}/><LanguageFlag code={game.targetLanguage} name={game.targetLanguage.toUpperCase()}/></>:<span>Sem modelo</span>}</div>
                <div className="status"><i className={`dot ${isRunning?"ok":game.status === "Instalação pendente"?"warn":""}`}/>{isRunning?visibleStatus:game.status === "Instalação pendente" ? "Abra o jogo para iniciar a instalação" : visibleStatus}</div>
              </div>
            </div>
            <time className="game-last-launch"><span>Última execução</span><b>{game.lastLaunch?new Date(game.lastLaunch).toLocaleString("pt-BR",{dateStyle:"short",timeStyle:"short"}):"Nunca iniciado"}</b></time>
            <div className="row-actions">{game.id===activeGameId?<><button className="play-action" onClick={onConsole} title="Abrir console" aria-label={`Abrir console de ${game.name}`}><Terminal size={17}/></button><button className="stop-action" onClick={onStop} title="Encerrar jogo" aria-label={`Encerrar ${game.name}`}><Square size={13} fill="currentColor"/></button></>:<button className="play-action" onClick={()=>onLaunch(game)} title={isTestOnlyGame(game)?"Abrir para teste, sem tradução":game.engine==="RPG Maker"?`Iniciar tradução ${game.runtime} experimental`:"Iniciar jogo"} aria-label={`Iniciar ${game.name}`}><Play size={17} fill="currentColor"/></button>}<button className="more-action" onClick={()=>onSelect(game)} title="Editar jogo"><Pencil size={15}/></button><button className="model-delete" onClick={()=>onDelete(game)} title="Remover jogo" aria-label={`Remover ${game.name}`}><Trash2 size={15}/></button></div>
          </article>})}
        </section>}
  </div>;
}
