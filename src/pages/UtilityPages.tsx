import { useEffect, useRef, type ReactNode } from "react";
import { Activity, ChevronLeft, Download, Gamepad2, Play, Square, Wrench, X } from "lucide-react";
import type { AppSettings, EngineHealth, Game, DownloadTask, SessionLine } from "../types";
import { PageHeading } from "../components/Common";
import { isTestOnlyGame } from "../engines";

export function Diagnostics({ health, onAddRpgMaker, onAddUnreal }: { health: EngineHealth[]; onAddRpgMaker: () => void; onAddUnreal: () => void }) {
  return <div className="page"><PageHeading eyebrow="SAÚDE DO SISTEMA" title="Diagnósticos" text="Estado real de cada motor nesta instalação."/><section className="diagnostic-grid">
    {health.map(h=><article key={h.engine} className={h.development?"diag-development":undefined}>
      <div className="diag-head"><div className="panel-icon">{h.development?<Gamepad2 size={20}/>:<Wrench size={20}/>}</div><div><h3>Motor {h.engine}</h3><p>{h.details}</p></div></div>
      {h.development?h.engine==="RPG Maker"?<><span className="pill neutral">Todas as famílias em teste experimental</span><p className="development-explanation">MV/MZ instalam plugin JavaScript; Unite usa BepInEx/XUnity. RPG Maker 95, 2000/2003 e XP/VX/VX Ace tentam OCR local com texto sobreposto, sem alterar o jogo. O resultado depende do idioma OCR instalado no Windows, da janela do jogo e do texto visível; telas exclusivas ou letras desenhadas em imagens podem falhar. Ainda não há validação real nessas versões antigas.</p><Check label="Servidor Argos integrado" value={h.runtimeFound}/><Check label="Algum modelo offline" value={h.modelFound}/><button className="secondary" onClick={onAddRpgMaker}>Cadastrar RPG Maker para teste</button></>:<><span className="pill neutral">Unreal experimental · por jogo</span><p className="development-explanation">CatIslandPetrichor e Woman Simulator traduzem widgets UMG selecionados com o Argos local. Os botões do menu de Woman Simulator foram identificados no log; a aplicação visual ainda precisa de teste. Outros títulos Unreal ainda abrem sem hook.</p><Check label="Hook e Argos empacotados" value={h.runtimeFound}/><Check label="Algum modelo offline" value={h.modelFound}/><button className="secondary" onClick={onAddUnreal}>Cadastrar Unreal para teste</button></>:<><Check label="Código-fonte" value={h.sourceFound}/><Check label="Runtime empacotado" value={h.runtimeFound}/><Check label="Modelo offline" value={h.modelFound}/></>}
    </article>)}
    <article className="diag-coming"><div className="diag-head"><div className="panel-icon"><Activity size={20}/></div><div><h3>Próximo motor</h3><p>Ajude a definir qual integração será desenvolvida a seguir.</p></div></div><span className="pill neutral">Votação · em breve</span><p>A votação aparecerá aqui quando a próxima rodada estiver disponível.</p></article>
  </section></div>;
}
function Check({label,value}:{label:string;value:boolean}) { return <div className="check"><span>{label}</span><b className={value?"good":"muted"}>{value?"Encontrado":"Não confirmado"}</b></div>; }
export function SettingsPage({settings,onChange,updates}:{settings:AppSettings;onChange:(settings:AppSettings)=>void;updates?:ReactNode}) { return <div className="page"><PageHeading eyebrow="PREFERÊNCIAS" title="Configurações" text="A nova base manterá modelos e dados fora das pastas dos jogos."/><section className="settings-card"><div><h3>Tema</h3><p>Interface escura</p><span className="switch on"><i/></span></div><div><h3>Idioma da interface</h3><p>Português (Brasil)</p><button className="secondary">Alterar</button></div><div className="experimental-setting"><div><h3>Fluxo encadeado experimental</h3><p>Libera 1 → EN → 2 quando não existir modelo direto. Usa duas etapas no mesmo servidor local.</p></div><button type="button" className={`switch ${settings.enableExperimentalChainedFlow?"on":""}`} aria-pressed={settings.enableExperimentalChainedFlow} onClick={()=>onChange({...settings,enableExperimentalChainedFlow:!settings.enableExperimentalChainedFlow})}><i/></button></div>{updates}</section></div>; }
export function DownloadsPage({tasks}:{tasks:DownloadTask[]}) { return <div className="page"><PageHeading eyebrow="OPERAÇÕES" title="Downloads" text="Acompanhe modelos e componentes sem bloquear o restante do aplicativo."/>{tasks.length?<section className="downloads-list">{tasks.map(task=><article key={task.id} className={task.status}><div className="download-status">{task.status==="baixando"?<span className="spinner"/>:task.status==="concluído"?<Activity size={19}/>:<X size={19}/>}</div><div className="download-copy"><h3>{task.name}</h3><p>{task.detail}</p>{task.status==="baixando"&&<div className="progress-track"><i style={{width:`${task.progress}%`}}/></div>}</div><span className="download-label">{task.status}</span></article>)}</section>:<section className="empty-card compact"><div className="panel-icon"><Download size={24}/></div><h2>Nenhum download por enquanto</h2><p>Os modelos iniciados em Modelos Universais aparecerão aqui.</p></section>}</div>; }
export function SessionPage({game,lines,running,onBack,onRestart,onStop}:{game:Game;lines:SessionLine[];running:boolean;onBack:()=>void;onRestart:()=>void;onStop:()=>void}) {
  const testOnly=isTestOnlyGame(game);
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
    <header><button className="back-button" onClick={onBack}><ChevronLeft size={15}/>Biblioteca</button><div className="session-actions"><div><span className={`session-dot ${running?"live":""}`}/><b>{game.name}</b><small>{running?(testOnly?"teste sem tradução":game.engine==="RPG Maker"?`tradução ${game.runtime} experimental`:"tradução em tempo real"):"jogo encerrado"}</small></div>{running?<button className="stop-action session-stop" onClick={onStop}><Square size={12} fill="currentColor"/>Encerrar jogo</button>:<button className="primary session-restart" onClick={onRestart}><Play size={15}/>Iniciar novamente</button>}</div></header>
    <section className="terminal">
      <div className="terminal-head"><span>SFTranslator runtime</span><span>{testOnly?"Teste sem tradução":`${game.sourceLanguage.toUpperCase()} → ${game.targetLanguage.toUpperCase()}`}</span></div>
      <div className="terminal-output" ref={outputRef} onScroll={updateScrollFollow}>{lines.length?lines.map((line,index)=><p key={index} className={line.kind}><i>{line.kind==="error"?"!":line.kind==="system"?"›":"·"}</i>{line.text}</p>):<p className="system"><i>›</i>{testOnly?"Preparando abertura do jogo para teste, sem tradução…":"Aguardando saída do motor de tradução…"}</p>}</div>
      <footer><span>{testOnly?"Saída do jogo (sem tradução)":"Saída do tradutor"}</span><b>{running?"acompanhando":"finalizada"}</b></footer>
    </section>
  </div>;
}
export function EmptyPage({icon:Icon,title,text}:{icon:typeof Download;title:string;text:string}) { return <div className="page"><PageHeading title={title} text={text}/><section className="empty-card compact"><div className="panel-icon"><Icon size={24}/></div><h2>Nenhuma atividade por enquanto</h2><p>Esta área será ativada durante a migração dos fluxos de instalação.</p></section></div>; }
