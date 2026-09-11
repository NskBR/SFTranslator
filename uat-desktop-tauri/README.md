# SFTranslator — Tauri 2

Nova interface unificada para os tradutores UAT Ren'Py e UAT Unity.

## Desenvolvimento

```powershell
npm install
npm run tauri dev
```

O backend Rust já detecta jogos Unity (Mono/IL2CPP e arquitetura) e Ren'Py, e persiste a biblioteca no diretório de dados da aplicação. Os motores Python legados permanecem intactos nas pastas vizinhas enquanto seus fluxos são migrados e testados.

## Catálogo e modelos

O catálogo oficial Argos está incluído em `src-tauri/resources/argos-index.json` e é incorporado ao executável. Uma cópia nova do repositório não precisa ter `models/argos-translate/index.json` para listar ou baixar fluxos. O índice local, quando válido, complementa o catálogo incluído. Para atualizar o catálogo distribuído, substitua esse recurso pelo JSON de https://raw.githubusercontent.com/argosopentech/argospm-index/main/index.json e execute `cargo test --lib` em `src-tauri`.

Os modelos instalados são detectados pelos arquivos `metadata.json` em `uat-renpy/models/argos-translate/packages`, independentemente do catálogo. Downloads temporários não são considerados instalados. Sem uma pasta de motores disponível, os downloads usam `models` no diretório de dados da aplicação. Ambos os servidores recebem esse caminho por `UAT_MODELS_DIR`.

A localização dos motores considera a pasta do executável, o diretório de trabalho e a pasta de compilação, nessa ordem. Os runtimes `lt.exe` continuam sendo necessários para traduzir jogos; o catálogo incluído não substitui esses runtimes, que não são versionados no Git.
