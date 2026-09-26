# Arquitetura dos motores

O SFTranslator separa a integração com cada jogo da tradução local. Os modelos Argos são instalados uma vez no diretório de dados do aplicativo e podem ser usados por qualquer motor compatível. O console recebe os eventos da sessão compartilhada; abrir um jogo inicia somente o adaptador daquele motor e seu servidor local.

## Onde fica cada parte

| Parte | Local | Responsabilidade |
| --- | --- | --- |
| Registro e contrato | `src-tauri/src/engines/mod.rs` | Reconhecimento, integração, cache, início da sessão e diagnóstico |
| Ren'Py | `src-tauri/src/engines/renpy/mod.rs` e `engines/uat-renpy/` | Hook moderno/legado, configuração e servidor local |
| Unity | `src-tauri/src/engines/unity/mod.rs` e `engines/uat-unity/` | Instalação BepInEx/XUnity para Mono ou IL2CPP, configuração e servidor local |
| RPG Maker | `src-tauri/src/engines/rpgmaker/` e `engines/rpgmaker/js/SFTranslator.js` | MV/MZ experimentais com plugin JavaScript e Argos local; demais versões em teste de cadastro |
| Unreal | `src-tauri/src/engines/unreal/` e `engines/unreal/observer.lua` | Tradução UMG experimental no CatIslandPetrichor e no menu do Woman Simulator |
| Sessão compartilhada | `src-tauri/src/session.rs` | Console, processo do jogo, espera do servidor e encerramento |
| Modelos compartilhados | `src-tauri/src/models.rs` e `src-tauri/src/catalog.rs` | Catálogo, downloads e pacotes instalados |
| Apresentação | `src/engines/` | Rótulo do cache e estilo de cada motor na interface |
| Empacotamento | `scripts/build-runtimes.py` e `src-tauri/build.rs` | Inclusão dos runtimes no instalador |

O contrato `EngineAdapter` mantém as diferenças de cada jogo fora da sessão comum. Para adicionar um motor integrado, crie uma pasta em `src-tauri/src/engines/`, implemente o contrato e registre o adaptador em `engines/mod.rs`. Inclua o runtime no empacotamento, adicione a apresentação em `src/engines/` e valide reconhecimento, instalação, tradução, cache e encerramento.

O RPG Maker MV/MZ instala um plugin próprio no primeiro início, após salvar uma cópia de `js/plugins.js` em `js/plugins.js.sftranslator.bak` (dentro de `www` quando houver). Ambos compartilham o código JavaScript de tradução e usam adaptadores separados para identificar e iniciar cada família. O plugin intercepta diálogos e escolhas, traduz nomes de mapas e termos padrão de menu em memória, protege códigos de controle e usa o servidor Argos integrado. O cache fica em `uat-rpgmaker/cache/<fluxo>/translations.json` na pasta do jogo quando NW.js oferece acesso a arquivos; no navegador, `localStorage` é o fallback. O botão Limpar invalida também esse fallback no próximo início. O estado do servidor fica no diretório de dados do aplicativo. O suporte ainda é experimental: rótulos gravados em imagens e interfaces particulares de plugins de terceiros não são traduzidos automaticamente.

A verificação de instalação do MV/MZ exige tanto o arquivo do plugin quanto uma entrada ativa em `js/plugins.js`. Nomes de mapas cujo pedido falhou são tentados novamente após cinco segundos. O idioma de MV/MZ é lido de `data/System.json` quando o campo `locale` está presente; a configuração do usuário não é alterada automaticamente quando a detecção muda.

Verificações MV/MZ: `npm run test:rpgmaker` testa o plugin isolado; `cargo run --example verify_mz_registration -- "<pasta do jogo>"` e `cargo run --example verify_mv_registration -- "<pasta do jogo>"` testam o registro e o backup em cópias temporárias de `plugins.js`; `node scripts/smoke-rpgmaker-mz.cjs "<diretório dos modelos>" en pb direct "Living Room"` atravessa o plugin e o servidor Argos empacotado com modelos reais. Essas verificações não substituem uma partida no jogo com seu conjunto de plugins.

O adaptador também reconhece inicialmente XP, VX, VX Ace e 2000/2003 por arquivos de estrutura; 95 e Unite podem ser cadastrados manualmente em Diagnósticos. Nessas famílias o jogo abre sem tradução e mantém o status "Em desenvolvimento". A cobertura funcional solicitada inclui 95, 2000/2003, XP/VX/VX Ace, MV/MZ e Unite. XP/VX/VX Ace usam RGSS/Ruby, e 95/2000/2003 exigem avaliação separada da interceptação de texto. Unite é baseado em Unity, mas a compatibilidade com o adaptador Unity existente precisa de um jogo de teste.

`Midnight Exploration V 0.2.4 Bug Fix` é o jogo MZ de teste. `Daily Lives of My Countryside v0.3.5.3` contém `www/js/rpg_*.js` versão 1.6.1 e é o jogo MV de teste. Neste último, o registro do plugin foi validado em cópia temporária do `plugins.js` real e a tradução EN → PB foi validada com o runtime Argos real. As imagens do jogo usam o formato criptografado `.rpgmvp`; os três arquivos `.png` presentes passaram pela verificação de integridade. Ainda falta uma partida de validação do plugin dentro desse jogo. Faltam jogos representativos das outras famílias.

O registro atual é compilado com o aplicativo. Instalar um motor criado por terceiros sem recompilar exigirá um contrato de processo e um manifesto de permissões/versionamento; carregar código arbitrário na aplicação ainda não faz parte desta versão.

O adaptador Unreal reconhece executáveis associados a `Content/Paks` com `.pak` ou `.utoc`, incluindo launchers junto à pasta do projeto e binários `Binaries/Win64`. Para **CatIslandPetrichor** e **Woman Simulator** ele instala uma cópia empacotada e com hash verificado do UE4SS experimental, com apenas o mod `SFTranslatorObserver` ativado. O hook observa `TextBlock:SetText` e `RichTextBlock:SetText`; os textos elegíveis seguem por uma fila local até a mesma instância Argos embutida, com cache em `uat-unreal/cache/<fluxo>` e retorno ao widget enquanto o original ainda estiver visível. O log já registrou aplicações em botões de menu, mas a validação visual de diálogos continua pendente. No Woman Simulator, os botões observados do menu principal usam o mesmo servidor Argos; a aplicação visual ainda depende de teste. A integração recusa sobrescrever `dwmapi.dll` ou `ue4ss` preexistente de terceiros e inicia o binário Shipping diretamente. Outros jogos Unreal continuam abrindo sem hook. O build de distribuição inclui UE4SS via `npm run runtimes`; não há download desse componente no computador do usuário durante a partida.

O mapeamento das superfícies de texto e a proposta de hook estão em [Estudo do hook Unreal](UNREAL_HOOK_RESEARCH.md).

Referências técnicas: [plugins do RPG Maker MV](https://rpgmakerofficial.com/product/MV_Help/page/01_11_03.html), [RGSS do RPG Maker XP](https://rpgmakerweb.com/products/rpg-maker-xp), [RGSS3 do VX Ace](https://www.rpgmakerweb.com/products/rpg-maker-vx-ace), [pacotes de execução das versões 2000/2003](https://www.rpgmakerweb.com/downloads) e [Unite baseado em Unity](https://rpgmakerweb.com/blog/the-rpg-maker-festival-hits-steam).
