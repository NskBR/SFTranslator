export type Engine = string;

export interface Game {
  id: string;
  name: string;
  executablePath: string;
  engine: Engine;
  runtime?: string;
  suggestedRpgMakerFamily?: string;
  architecture?: string;
  status: "Novo" | "Pronto" | "Atenção" | "Instalação pendente" | "Modelo necessário" | "Em desenvolvimento" | "Em teste";
  sourceLanguage: string;
  targetLanguage: string;
  addedAt: string;
  lastLaunch?: string;
  iconData?: string;
  modelInstalled: boolean;
  detectedLanguage?: string;
  languageConfidence?: number;
  integrationStatus?: string;
  flowMode: "direct" | "chain";
  intermediateLanguage?: string;
}

export interface AppSettings {
  enableExperimentalChainedFlow: boolean;
  enableTrayMode: boolean;
  theme: "amber" | "ocean" | "violet" | "contrast" | "crimson" | "forest";
  appearance: ThemePreferences;
}

export interface ThemePreferences {
  accent: string | null;
  background: string | null;
  panel: string | null;
  surface: string | null;
  font: "system" | "serif" | "mono";
  gradient: "none" | "aurora" | "sunset" | "ocean" | "cyberpunk";
  gradientAngle: number;
  animations: boolean;
  animatedIcons: boolean;
  iconStyle: "default" | "accent" | "soft";
  imageId: string | null;
  localThemeId: string | null;
  officialThemeId: string | null;
  localThemeVariant: number;
  customCss: string;
}

export interface EngineHealth {
  engine: string;
  sourceFound: boolean;
  runtimeFound: boolean;
  modelFound: boolean;
  development?: boolean;
  details: string;
}

export interface TranslationModel {
  id: string;
  fromCode: string;
  fromName: string;
  toCode: string;
  toName: string;
  version: string;
  installed: boolean;
  usedBy: number;
}

export type DownloadTask = {id:string; modelId:string; name:string; status:"baixando"|"concluído"|"erro"; detail:string; progress:number};
export type SessionLine = {kind:string; text:string};
