# Motores integrados do SFTranslator

A raiz do repositório é a raiz do aplicativo: `engines/` contém os adaptadores, `scripts/` as ferramentas, `.venv/` o ambiente de build, `logs/` os registros locais e `docs/history/` a documentação histórica. Os documentos históricos descrevem etapas anteriores e não são instruções do build atual.

O instalador inclui os executáveis congelados, Python, bibliotecas nativas e MiniSBD. O usuário final não instala Python, pip ou LibreTranslate.

## Organização

- `src/` e `src-tauri/`: interface, biblioteca, catálogo, downloads e controle dos servidores.
- `engines/uat-renpy`: fontes do adaptador Ren'Py e servidor LibreTranslate. Os hooks são copiados para o jogo; o servidor permanece no aplicativo.
- `engines/uat-unity`: fontes do adaptador Unity, servidor Argos com API de tradução e instalador BepInEx/XUnity.

As pastas dos adaptadores são entradas do build. A instalação final não depende do checkout GitHub. Cada sessão usa o servidor do motor selecionado; a cadeia executa duas traduções na mesma instância.

## Build

Na máquina de build são necessários Windows x64, Python 3.12, Node.js, Rust e ferramentas Tauri.

```powershell
npm install
npm run runtimes
npm run tauri dev
# Para gerar instaladores completos:
npm run release
```

Na raiz do repositório, `runtimes` cria `.venv`, instala `scripts/runtime-requirements.txt` e compila os motores. MiniSBD entra no pacote; modelos de tradução pessoais não entram. `release` executa essa preparação automaticamente. A compilação Rust de distribuição rejeita motores ausentes.

```text
SFTranslator/
  uat-desktop.exe
  runtimes/
    manifest.json
    minisbd/
    renpy/lt.exe + _internal/ + uat/ + game/
    unity/lt.exe + _internal/
```

Os diretórios `_internal` contêm Python e bibliotecas nativas; nunca distribua somente os executáveis.

## Dados e downloads

Modelos são compartilhados em `app_data_dir()/models`, para o identificador `com.uat.desktop`. Na primeira utilização, modelos da antiga pasta `engines/uat-renpy/models` são copiados quando o checkout está disponível. Configurações e logs específicos ficam nas pastas de integração do jogo. Os servidores não gravam na instalação do aplicativo.

O catálogo Argos é incorporado ao Rust. Modelos de tradução são baixados pelo SFTranslator conforme os pares escolhidos. Unity baixa BepInEx/XUnity conforme Mono/IL2CPP e arquitetura. Ren'Py recebe hooks já incluídos. Não ocorre instalação de Python ou LibreTranslate no computador do usuário.

## Verificação

```powershell
cargo test --lib --manifest-path src-tauri/Cargo.toml
.\.venv\Scripts\python.exe -m unittest discover -s engines/uat-unity/tests
.\.venv\Scripts\python.exe scripts/smoke-runtimes.py --models engines/uat-renpy/models
```

O smoke test exige `ja-en` e `en-pb`. Inicia ambos os executáveis em pastas temporárias, sem Python no PATH, verifica traduções reais e encerra os processos.
