import React from "react";
import ReactDOM from "react-dom/client";
import { invoke } from "@tauri-apps/api/core";
import { getCurrentWindow } from "@tauri-apps/api/window";
import App from "./App";
import type { AppSettings } from "./types";
import { applyTheme } from "./theme/applyTheme";
import "./translator-ui.css";
import "./theme/appearance.css";

async function start() {
  const inTauri = "__TAURI_INTERNALS__" in window;
  let bootSettings: AppSettings | undefined;
  if (inTauri) {
    try {
      bootSettings = await invoke<AppSettings>("get_settings");
      await applyTheme(bootSettings);
    } catch (error) {
      console.error("Não foi possível preparar o tema inicial:", error);
    }
  }
  ReactDOM.createRoot(document.getElementById("root")!).render(<React.StrictMode><App bootSettings={bootSettings}/></React.StrictMode>);
  if (inTauri) {
    await document.fonts.ready;
    await new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve())));
    await getCurrentWindow().show();
  }
}

void start().catch(error => console.error("Falha ao iniciar a interface:", error));
