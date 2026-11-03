import { useCallback, useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { BarChart3, RefreshCw } from "../components/icons";

type MetricsSnapshot = { translatedWords: number; workedGames: number; failedGames: number };
const format = (value: number) => new Intl.NumberFormat("pt-BR").format(value);

export function MetricsPage() {
  const [metrics, setMetrics] = useState<MetricsSnapshot>();
  const [error, setError] = useState<string>();
  const load = useCallback(async () => {
    try {
      setMetrics(await invoke<MetricsSnapshot>("translation_metrics"));
      setError(undefined);
    } catch (reason) {
      setError(String(reason));
    }
  }, []);

  useEffect(() => {
    void load();
    let timeout: number | undefined;
    const listener = listen("metrics-updated", () => {
      window.clearTimeout(timeout);
      timeout = window.setTimeout(() => void load(), 300);
    });
    return () => {
      window.clearTimeout(timeout);
      void listener.then(unlisten => unlisten());
    };
  }, [load]);

  const worked = metrics?.workedGames ?? 0;
  const failed = metrics?.failedGames ?? 0;
  const total = worked + failed;
  const percent = total ? Math.round(worked / total * 100) : 0;

  return <section className="page translator-metrics-page">
    <header className="translator-metrics-header">
      <div><h1>Métricas</h1><p>Traduções e resultados de jogos registrados pelo SFTranslator.</p></div>
      <button type="button" className="secondary" onClick={() => void load()}><RefreshCw size={16}/> Atualizar</button>
    </header>
    {error && <p className="translator-metrics-error" role="alert">Não foi possível carregar as métricas: {error}</p>}
    <div className="translator-metrics-layout">
      <section className="translator-metrics-chart" aria-label="Distribuição dos jogos com resultado registrado">
        <h2>Resultado dos jogos</h2>
        <div className="translator-metrics-donut" style={{ background: total ? `conic-gradient(var(--ready) 0 ${percent}%, var(--danger) ${percent}% 100%)` : "var(--surface-2)" }}>
          <div><strong>{format(total)}</strong><span>com resultado</span></div>
        </div>
        <div className="translator-metrics-legend"><span><i className="success"/>Funcionaram</span><b>{format(worked)}</b></div>
        <div className="translator-metrics-legend"><span><i className="failure"/>Falharam</span><b>{format(failed)}</b></div>
      </section>
      <div className="translator-metrics-cards">
        <article className="translator-metric-card hero"><div className="translator-metric-heading"><BarChart3 size={18}/><span>Palavras traduzidas</span></div><strong>{format(metrics?.translatedWords ?? 0)}</strong><p>Palavras produzidas pelos motores durante sessões monitoradas.</p></article>
        <article className="translator-metric-card success"><span>Jogos que funcionaram</span><strong>{format(worked)}</strong><p>Jogos com ao menos uma tradução registrada após a última falha de sessão.</p></article>
        <article className="translator-metric-card failure"><span>Jogos que falharam</span><strong>{format(failed)}</strong><p>Jogos cuja última sessão monitorada terminou com erro de preparação ou execução.</p></article>
      </div>
    </div>
    <p className="translator-metrics-note">A contagem começa nesta versão e separa palavras por espaços no texto traduzido. Abrir o jogo sem tradução registrada não é considerado sucesso; textos vindos do cache antigo não entram no total.</p>
  </section>;
}
