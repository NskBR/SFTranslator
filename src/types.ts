export type Engine = "Unity" | "Ren'Py" | "Desconhecido";

export interface Game {
  id: string;
  name: string;
  executablePath: string;
  engine: Engine;
  runtime?: string;
  architecture?: string;
  status: "Novo" | "Pronto" | "Atenção" | "Instalação pendente" | "Modelo necessário";
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
}

export interface EngineHealth {
  engine: string;
  sourceFound: boolean;
  runtimeFound: boolean;
  modelFound: boolean;
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
