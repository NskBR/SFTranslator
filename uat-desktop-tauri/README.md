# SFTranslator — Tauri 2

Aplicativo unificado com motores Ren'Py e Unity empacotados no instalador. Consulte [RUNTIME.md](RUNTIME.md) para arquitetura, dependências e verificação.

## Desenvolvimento

```powershell
npm install
npm run runtimes
npm run tauri dev
```

O backend Rust detecta jogos Unity (Mono/IL2CPP e arquitetura) e Ren'Py e persiste a biblioteca no diretório de dados da aplicação. As pastas em `engines/` contêm os fontes dos adaptadores usados para gerar os motores integrados.

## Catálogo e modelos

O catálogo oficial Argos está incluído em `src-tauri/resources/argos-index.json` e é incorporado ao executável. Uma cópia nova do repositório não precisa ter `models/argos-translate/index.json` para listar ou baixar fluxos. O índice local, quando válido, complementa o catálogo incluído. Para atualizar o catálogo distribuído, substitua esse recurso pelo JSON de https://raw.githubusercontent.com/argosopentech/argospm-index/main/index.json e execute `cargo test --lib` em `src-tauri`.

Os modelos instalados são detectados pelos arquivos `metadata.json` em `models/argos-translate/packages` no diretório de dados da aplicação, independentemente do catálogo. Downloads temporários não são considerados instalados. Ambos os servidores recebem esse caminho por `UAT_MODELS_DIR`.

A localização dos motores usa os recursos instalados do aplicativo. `npm run release` gera os runtimes e os inclui no instalador; os binários gerados não são versionados no Git. Modelos são mantidos no diretório de dados do aplicativo, com cópia inicial dos modelos legados quando disponíveis.
