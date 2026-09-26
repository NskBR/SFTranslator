import { useEffect, useState } from "react";
import { Activity, Box, ChevronRight, Download, Gamepad2, Languages, Trash2, Wrench, X } from "lucide-react";
import type { Game, TranslationModel } from "../types";
import { LanguageFlag, UiSelect } from "../components/LanguageControls";
import { PageHeading } from "../components/Common";

export function Models({ models, games, onOpenGame, onDelete, onDownload }: { models: TranslationModel[]; games:Game[]; onOpenGame:(game:Game)=>void; onDelete:(model:TranslationModel)=>void; onDownload:(model:TranslationModel)=>Promise<boolean> }) {
  const [showCatalog,setShowCatalog]=useState(false);
  const available=models.filter(model=>!model.installed);
  const installed=models.filter(model=>model.installed).sort((left, right) => {
    const usage = (model: TranslationModel) => games.filter(game => game.modelInstalled && game.sourceLanguage === model.fromCode && game.targetLanguage === model.toCode).length;
    return usage(right) - usage(left) || left.fromName.localeCompare(right.fromName);
  });
  const [showAllInstalled, setShowAllInstalled] = useState(false);
  const hiddenInstalledCount = Math.max(0, installed.length - 2);
  useEffect(() => {
    const grid = document.querySelector<HTMLElement>(".models-page .model-grid");
    if (!grid) return;
    const page = grid.closest<HTMLElement>(".models-page");
    page?.classList.toggle("models-expanded", showAllInstalled);
    const cards = Array.from(grid.querySelectorAll<HTMLElement>(":scope > article"));
    cards.forEach((card, index) => { card.hidden = !showAllInstalled && index >= 2; });
    if (hiddenInstalledCount === 0) return () => page?.classList.remove("models-expanded");
    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "show-more-models";
    toggle.textContent = showAllInstalled ? "Mostrar menos" : `Ver mais modelos (${hiddenInstalledCount})`;
    toggle.addEventListener("click", () => setShowAllInstalled(expanded => !expanded));
    grid.insertAdjacentElement("afterend", toggle);
    return () => { if (toggle.parentElement) toggle.remove(); page?.classList.remove("models-expanded"); };
  }, [showAllInstalled, hiddenInstalledCount, installed.length]);
  const sources=Array.from(new Map(available.map(model=>[model.fromCode,{code:model.fromCode,name:model.fromName}])).values()).sort((a,b)=>a.name.localeCompare(b.name));
  const [source,setSource]=useState("");
  const destinations=available.filter(model=>model.fromCode===source).sort((a,b)=>a.toName.localeCompare(b.toName));
  const [selectedId,setSelectedId]=useState("");
  useEffect(()=>{if(showCatalog&&!sources.some(item=>item.code===source))setSource(sources[0]?.code||"");},[showCatalog,models]);
  useEffect(()=>{if(!destinations.some(model=>model.id===selectedId))setSelectedId(destinations[0]?.id||"");},[source,models]);
  const selected=models.find(model=>model.id===selectedId);
  const install=async()=>{if(selected){await onDownload(selected);setShowCatalog(false);}};
  const configuredGames=games.filter(game=>game.modelInstalled).length;
  return <div className="page models-page"><PageHeading eyebrow="FLUXOS ARGOS" title="Modelos universais" text="Fluxos instalados e compartilhados por todos os motores." action={<button className="primary" onClick={()=>setShowCatalog(true)}><Download size={16}/>Baixar modelo</button>}/><div className="universal-note"><Languages size={19}/><div><b>Os modelos são pares direcionados</b><span>A disponibilidade é definida pelo catálogo Argos: ter japonês como origem não significa que todos os destinos existem.</span></div></div><section className="models-overview"><article><Box size={20}/><div><span>Instalados</span><b>{installed.length}</b><small>fluxos universais prontos</small></div></article><article><Gamepad2 size={20}/><div><span>Jogos configurados</span><b>{configuredGames}</b><small>usando modelos locais</small></div></article><article><Download size={20}/><div><span>No catálogo</span><b>{available.length}</b><small>fluxos disponíveis para baixar</small></div></article></section><section className="model-grid">{installed.length ? installed.map(model=>{const modelGames=games.filter(game=>game.modelInstalled&&game.sourceLanguage===model.fromCode&&game.targetLanguage===model.toCode);return <article key={model.id} className="installed"><header className="model-card-head"><div className="model-flag-flow"><LanguageFlag code={model.fromCode} name={model.fromName}/><ChevronRight size={16}/><LanguageFlag code={model.toCode} name={model.toName}/></div><span className="pill success">Instalado</span></header><div className="model-card-copy"><h3>{model.fromName} → {model.toName}</h3><p>Fluxo offline do Argos Translate, compartilhado entre os motores compatíveis.</p></div><div className="model-stat-grid"><div><span>Versão</span><b>{model.version}</b></div><div><span>Compatibilidade</span><b>Motores locais</b></div></div><footer><div className="model-usage">{modelGames.length>0&&<div className="model-game-icons">{modelGames.map(game=><button key={game.id} onClick={()=>onOpenGame(game)} title={`Abrir ${game.name}`}>{game.iconData?<img src={game.iconData} alt=""/>:<Gamepad2 size={14}/>}</button>)}</div>}<small>{modelGames.length ? `${modelGames.length} ${modelGames.length===1?"jogo usando":"jogos usando"}` : "Disponível para todos os jogos"}</small></div><button className="model-delete" onClick={()=>onDelete(model)} title="Apagar modelo"><Trash2 size={14}/></button></footer></article>}) : <div className="no-models"><Box size={25}/><h3>Nenhum modelo instalado</h3><p>Use “Baixar modelo” acima para escolher um fluxo disponível.</p></div>}</section><section className="models-guide"><article><Languages size={19}/><div><b>Uso universal</b><span>Um único fluxo instalado atende os motores compatíveis.</span></div></article><article><Wrench size={19}/><div><b>Configuração por jogo</b><span>Escolha o par de idiomas na edição do jogo.</span></div></article><article><Activity size={19}/><div><b>Tradução local</b><span>Os fluxos funcionam pelo runtime local do SFTranslator.</span></div></article></section>{showCatalog&&<div className="modal-backdrop" onMouseDown={event=>{if(event.target===event.currentTarget)setShowCatalog(false)}}><section className="model-modal"><header><div><span className="eyebrow">CATÁLOGO ARGOS</span><h2>Baixar modelo</h2><p>Escolha uma origem; o destino exibirá somente pares existentes.</p></div><button onClick={()=>setShowCatalog(false)}><X size={18}/></button></header>{available.length?<><div className="form-row"><label>Idioma original<UiSelect value={source} options={sources.map(item=>({value:item.code,label:item.name}))} onChange={setSource} ariaLabel="Idioma original"/></label><label>Destino disponível<UiSelect value={selectedId} options={destinations.map(model=>({value:model.id,label:model.toName}))} onChange={setSelectedId} ariaLabel="Destino disponível"/></label></div>{selected&&<div className="catalog-selection"><div className="flow"><span>{selected.fromCode.toUpperCase()}</span><ChevronRight/><span>{selected.toCode.toUpperCase()}</span></div><div><b>{selected.fromName} → {selected.toName}</b><small>Argos Translate · versão {selected.version}</small></div></div>}<footer><button className="secondary" onClick={()=>setShowCatalog(false)}>Cancelar</button><button className="primary" disabled={!selected} onClick={install}><Download size={16}/>Baixar e instalar</button></footer></>:<div className="no-models"><Box/><h3>{models.length ? "Todos os fluxos estão instalados" : "Catálogo indisponível"}</h3>{!models.length && <p>Não foi possível carregar os fluxos. Reinicie o aplicativo e consulte os diagnósticos.</p>}</div>}</section></div>}</div>;
}
