import { Fragment, type MouseEvent, type RefObject } from "react";
import { Activity, Box, CircleHelp, Library, Maximize2, Minus, Terminal, X } from "../icons";
import { BarChart3, Download, Settings } from "../icons";
import logo from "../../assets/sftranslator-logo-v2.png";
import type { EngineHealth, Game } from "../../types";
import { isTestOnlyGame } from "../../engines";

const navigation = [
  ["Biblioteca", Library], ["Console", Terminal],
  ["Modelos", Box], ["Downloads", Download], ["Diagnósticos", Activity],
] as const;

export function AppTitlebar({ health, version, updateVersion, onUpdate, onMinimize, onMaximize, onClose, onDrag }: {
  health: EngineHealth[]; version: string; updateVersion?: string; onUpdate: () => void;
  onMinimize: () => void; onMaximize: () => void; onClose: () => void; onDrag: () => void;
}) {
  return <header className="titlebar" data-tauri-drag-region onMouseDown={event => { if (event.button === 0 && !(event.target as HTMLElement).closest("button")) onDrag(); }} onDoubleClick={event => { if (!(event.target as HTMLElement).closest("button")) onMaximize(); }}>
    <div className="titlebar-engines">{health.map(item => { const engine=item.engine; const online=Boolean(item.sourceFound&&item.runtimeFound&&!item.development); return <span key={engine} title={item.details}><i className={`dot ${item.development?(item.runtimeFound?"warn":""):online?"ok":""}`}/>{item.development?`${engine==="RPG Maker"?"RPGM":engine} · dev`:engine==="RPG Maker"?"RPGM":engine}</span>; })}</div>
    <div className="app-title" data-tauri-drag-region><strong>SFTranslator</strong><span>v{version}</span>{updateVersion && <button type="button" className="titlebar-update" onClick={onUpdate}>Atualização v{updateVersion}</button>}</div>
    <div className="window-actions"><button onClick={onMinimize} aria-label="Minimizar"><Minus size={16}/></button><button onClick={onMaximize} aria-label="Maximizar"><Maximize2 size={14}/></button><button className="close" onClick={onClose} aria-label="Fechar"><X size={17}/></button></div>
  </header>;
}

export function AppSidebar({ sidebarRef, width, compact, page, setPage, gamesCount, installedModelCount, sessionRunning, sessionGame, aboutOpen, aboutButtonRef, onAbout, onResize, onToggleWidth }: {
  sidebarRef: RefObject<HTMLElement>; width: number; compact: boolean; page: string; setPage: (page: string) => void;
  gamesCount: number; installedModelCount: number; sessionRunning: boolean; sessionGame?: Game;
  aboutOpen: boolean; aboutButtonRef: RefObject<HTMLButtonElement>; onAbout: () => void;
  onResize: (event: MouseEvent) => void; onToggleWidth: () => void;
}) {
  return <aside ref={sidebarRef} className={compact ? "sidebar-compact" : ""} style={{ width }}>
    <div className="sidebar-brand"><img src={logo} alt="SFTranslator"/></div>
    <nav>{navigation.map(([label, Icon],index) => <Fragment key={label}>{index===0&&<span className="nav-group-label">Biblioteca</span>}{index===2&&<span className="nav-group-label">Ferramentas</span>}<button title={compact ? label : undefined} className={page === label ? "active" : ""} onClick={() => setPage(label)}><Icon size={18}/><span>{label}</span>{label === "Biblioteca" && <b className="nav-count">{gamesCount}</b>}{label === "Console" && sessionRunning && <i className="console-live-dot" aria-label="Sessão ativa"/>}</button></Fragment>)}</nav>
    <section className="sidebar-overview"><span>VISÃO GERAL</span><div><button onClick={()=>setPage("Biblioteca")}><b>{gamesCount}</b><small>{gamesCount===1?"Jogo":"Jogos"}</small></button><button onClick={()=>setPage("Modelos")}><b>{installedModelCount}</b><small>{installedModelCount===1?"Modelo":"Modelos"}</small></button></div><p><i className={`dot ${sessionRunning?"ok":""}`}/>{sessionRunning?sessionGame&&isTestOnlyGame(sessionGame)?"Jogo aberto para teste":"Tradução em andamento":"Aplicativo pronto"}</p></section>
    <div className="sidebar-footer"><button className={page === "Configurações" ? "active" : ""} title="Configurações" aria-label="Configurações" onClick={() => setPage("Configurações")}><Settings size={18}/></button><button className={page === "Métricas" ? "active" : ""} title="Métricas" aria-label="Métricas" onClick={() => setPage("Métricas")}><BarChart3 size={18}/></button><button ref={aboutButtonRef} className={aboutOpen ? "active" : ""} title="Sobre" aria-label="Sobre o SFTranslator" onClick={onAbout}><CircleHelp size={18}/></button></div>
    <div className="sidebar-resizer" role="separator" aria-label="Redimensionar barra lateral" aria-orientation="vertical" onMouseDown={onResize} onDoubleClick={onToggleWidth}/>
  </aside>;
}
