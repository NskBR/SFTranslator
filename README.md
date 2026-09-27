# SFTranslator — Tauri 2

Aplicativo unificado com motores Ren'Py e Unity empacotados no instalador. RPG Maker MV/MZ têm tradução experimental via plugin JavaScript; RPG Maker Unite identificado pelos assemblies usa a integração Unity BepInEx/XUnity. Todos compartilham o mesmo Argos local. RPG Maker 95, 2000/2003 e XP/VX/VX Ace tentam OCR local experimental com sobreposição de texto na janela do jogo; não alteram arquivos do jogo e dependem dos idiomas OCR instalados no Windows. Ainda faltam testes com jogos dessas famílias. Unreal reconhece pacotes Windows e oferece tradução UMG experimental para widgets selecionados de CatIslandPetrichor e Woman Simulator. O menu principal do Woman Simulator foi identificado no log, mas a aplicação visual das traduções ainda precisa de teste. Consulte [RUNTIME.md](RUNTIME.md) para arquitetura, dependências e verificação.

Os adaptadores de cada motor, a sessão compartilhada e o catálogo de modelos estão descritos em [Arquitetura dos motores](docs/ENGINE_ARCHITECTURE.md).

## Desenvolvimento

Execute os comandos abaixo diretamente na raiz do repositório. `src/`, `src-tauri/`, `engines/` e `scripts/` pertencem ao mesmo aplicativo.

```powershell
npm install
npm run runtimes
npm run tauri dev
```

O backend Rust detecta jogos Unity (Mono/IL2CPP e arquitetura), Ren'Py e algumas famílias de RPG Maker e persiste a biblioteca no diretório de dados da aplicação. As pastas em `engines/` contêm os fontes dos adaptadores usados para gerar os motores de tradução integrados.

## Catálogo e modelos

O catálogo oficial Argos está incluído em `src-tauri/resources/argos-index.json` e é incorporado ao executável. Uma cópia nova do repositório não precisa ter `models/argos-translate/index.json` para listar ou baixar fluxos. O índice local, quando válido, complementa o catálogo incluído. Para atualizar o catálogo distribuído, substitua esse recurso pelo JSON de https://raw.githubusercontent.com/argosopentech/argospm-index/main/index.json e execute `cargo test --lib` em `src-tauri`.

Os modelos instalados são detectados pelos arquivos `metadata.json` em `models/argos-translate/packages` no diretório de dados da aplicação, independentemente do catálogo. Downloads temporários não são considerados instalados. Ambos os servidores recebem esse caminho por `UAT_MODELS_DIR`.

A localização dos motores usa os recursos instalados do aplicativo. `npm run release` gera os runtimes e os inclui no instalador; os binários gerados não são versionados no Git. Modelos são mantidos no diretório de dados do aplicativo, com cópia inicial dos modelos legados quando disponíveis.

## Atualizações no Windows

O aplicativo instalado consulta o release mais recente de [NskBR/SFTranslator](https://github.com/NskBR/SFTranslator/releases) ao abrir. A versão também pode ser verificada manualmente em **Configurações → Atualizações do aplicativo**. Quando há uma versão maior, ele baixa o instalador NSIS x64 oficial, confere tamanho e SHA-256 publicados pelo GitHub e só instala após o usuário clicar em **Instalar e reiniciar**. Um jogo ativo precisa ser encerrado antes da instalação. A instalação automática não é oferecida em `tauri dev`.

A versão `v0.1.0` já publicada não contém esse atualizador; usuários dela precisarão instalar manualmente a primeira versão que o inclua. Depois disso, a verificação automática passa a funcionar nas versões seguintes.

Para publicar uma atualização, aumente a mesma versão `X.Y.Z` em `package.json`, `src-tauri/Cargo.toml` e `src-tauri/tauri.conf.json`; execute `npm run release`; então publique um release GitHub com tag `vX.Y.Z` e anexe `release/SFTranslator_X.Y.Z_x64-setup.exe`. O instalador precisa ser o asset do release, não apenas um arquivo no código-fonte. O script também gera `release/SHA256SUMS.txt` para conferência. O atualizador requer o campo `digest` SHA-256 do asset na API do GitHub; releases antigos que oferecem somente MSI continuam disponíveis para instalação manual.
