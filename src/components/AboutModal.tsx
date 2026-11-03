import { useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { BookOpen, Boxes, Languages, Terminal, X } from "./icons";
import logo from "../assets/sftranslator-logo-v2.png";

export function AboutModal({ version, onClose }: { version: string; onClose: () => void }) {
  const [error, setError] = useState("");

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  const openRepository = async () => {
    try { await invoke("open_project_repository"); }
    catch (reason) { setError(`Não foi possível abrir o repositório: ${String(reason)}`); }
  };

  return <div className="modal-backdrop" onMouseDown={event => { if (event.target === event.currentTarget) onClose(); }}>
    <section className="about-modal" role="dialog" aria-modal="true" aria-labelledby="about-title" aria-describedby="about-description">
      <header className="about-modal-header">
        <img src={logo} alt=""/>
        <div><span>SFTRANSLATOR</span><h2 id="about-title">SFTranslator</h2></div>
        <button className="about-close" type="button" onClick={onClose} aria-label="Fechar informações sobre o aplicativo" autoFocus><X size={21}/></button>
      </header>
      <div className="about-modal-content">
        <p id="about-description" className="about-intro">Traduza jogos com modelos locais e acompanhe cada sessão pela biblioteca do aplicativo.</p>
        <div className="about-features">
          <span><Boxes size={17}/>Modelos compartilhados</span>
          <span><Languages size={17}/>Fluxo direto ou via inglês</span>
          <span><Terminal size={17}/>Console em tempo real</span>
          <span><BookOpen size={17}/>Biblioteca de jogos</span>
        </div>
        <p className="about-explanation">Adicione o executável, escolha os idiomas e baixe os modelos necessários. Ao iniciar o jogo, o SFTranslator prepara a integração do motor e usa o tradutor local. Ren’Py e Unity têm integração própria; RPG Maker e Unreal ainda estão em teste experimental.</p>
        <dl className="about-details">
          <div><dt>Versão</dt><dd>v{version}</dd></div>
          <div><dt>Autor</dt><dd>NskBR</dd></div>
          <div><dt>Tecnologia</dt><dd>Tauri 2 · React · Rust</dd></div>
          <div><dt>Tradução</dt><dd>Argos Translate local</dd></div>
        </dl>
        {error && <p className="about-error" role="alert">{error}</p>}
      </div>
      <footer className="about-modal-footer">
        <button type="button" className="about-repository" onClick={() => void openRepository()}>Repositório no GitHub</button>
        <button type="button" className="primary" onClick={onClose}>Fechar janela</button>
      </footer>
    </section>
  </div>;
}
