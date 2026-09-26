import type { ReactNode } from "react";
import { Download, Trash2, X } from "lucide-react";
import type { Game } from "../types";

export function DeleteGameModal({ game, onCancel, onConfirm }: { game: Game; onCancel: () => void; onConfirm: () => void }) {
  return <div className="modal-backdrop delete-game-backdrop" onMouseDown={event => { if (event.target === event.currentTarget) onCancel(); }}><section className="delete-game-modal" role="dialog" aria-modal="true" aria-labelledby="delete-game-title"><button className="modal-close" onClick={onCancel} aria-label="Fechar"><X size={18}/></button><div className="delete-game-icon"><Trash2 size={23}/></div><span className="eyebrow">REMOVER DA BIBLIOTECA</span><h2 id="delete-game-title">Remover “{game.name}”?</h2><p>Somente o cadastro no SFTranslator será removido. O executável, os arquivos do jogo e os modelos universais permanecem intactos.</p><div className="delete-game-path"><span>Executável preservado</span><b>{game.executablePath}</b></div><footer><button className="secondary" onClick={onCancel}>Cancelar</button><button className="danger-button" onClick={onConfirm}><Trash2 size={16}/>Remover jogo</button></footer></section></div>;
}

export function PageHeading({ eyebrow, title, text, action }: { eyebrow?: string; title: string; text: string; action?: ReactNode }) {
  return <div className="page-heading"><div>{eyebrow && <span className="eyebrow">{eyebrow}</span>}<h1>{title}</h1><p>{text}</p></div>{action}</div>;
}
