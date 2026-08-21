# UAT Desktop — Progresso

> Este arquivo deve ser atualizado ao final de cada sessão ou marco relevante.

## Estado geral

**Fase atual:** fundação concluída; biblioteca inicial em desenvolvimento.

**Última atualização:** 20/08/2026.

## Decisões confirmadas

- [x] Unificar UAT Ren'Py e UAT Unity em um aplicativo desktop.
- [x] Manter os motores como adaptadores separados.
- [x] Compartilhar modelos Argos entre os dois motores.
- [x] Criar biblioteca persistente de jogos.
- [x] Restaurar configurações ao selecionar jogo já conhecido.
- [x] Permitir baixar, validar, reparar e excluir modelos.
- [x] Mostrar quais jogos dependem de cada modelo.
- [x] Não ativar automaticamente rotas indiretas de tradução.
- [x] Utilizar Python 3.11.
- [x] Utilizar PySide6 + Qt Quick/QML.
- [x] Utilizar SQLite.
- [x] Gerar build PyInstaller `onedir` e instalador Inno Setup.
- [x] Manter os projetos legados intactos durante a migração.

## Inventário recebido

- [x] `uat-renpy` presente em `C:\Users\Skell\Documents\Projeto`.
- [x] `uat-unity` presente em `C:\Users\Skell\Documents\Projeto`.
- [x] Código-fonte dos dois tradutores localizado.
- [x] Builds antigos e dependências empacotadas identificados.
- [x] UAT Unity corrigido para modelos Argos antigos.
- [x] Mockup visual da biblioteca aprovado como referência.

## Marcos

| Marco | Estado | Observação |
|---|---|---|
| Planejamento e escolha da stack | Concluído | Python 3.11 + PySide6/QML + SQLite |
| Esqueleto do `uat-desktop` | Concluído | Ambiente isolado e dependências travadas |
| Tema e navegação principal | Concluído | Revisado conforme o mockup aprovado |
| Banco e biblioteca de jogos | Em andamento | Persistência e adição inicial funcionam |
| Adaptador Unity | Pendente | Extrair sem regressão |
| Adaptador Ren'Py | Pendente | Preservar hooks modernos/legados |
| Modelos compartilhados | Pendente | Cache central e referências |
| Instalação Unity pela GUI | Pendente | BepInEx/XUnity e diagnóstico |
| Instalação Ren'Py pela GUI | Pendente | Provedores, cache e watchdog |
| Build portátil | Pendente | Windows sem Python |
| Instalador | Pendente | Inno Setup |
| Release candidata | Pendente | Após matriz de testes |

## Próximas tarefas

- [x] Criar a pasta `uat-desktop`.
- [x] Criar `pyproject.toml` e ambiente Python 3.11.
- [x] Adicionar PySide6, pytest, pytest-qt, Ruff e HTTPX.
- [x] Gerar `uv.lock`.
- [x] Criar a janela QML principal.
- [x] Implementar tokens do tema escuro.
- [x] Criar navegação lateral e páginas iniciais.
- [x] Criar o banco SQLite e sua primeira migração.
- [x] Definir as entidades iniciais e os estados dos jogos.
- [x] Implementar seleção de executável e persistência na biblioteca.
- [x] Implementar detecção inicial de Unity e Ren'Py.
- [ ] Adicionar busca e filtros funcionais à biblioteca.
- [ ] Implementar detalhes e remoção de jogo.
- [ ] Expandir a detecção usando os adaptadores legados.
- [ ] Implementar o assistente completo.

## Bloqueios atuais

- Nenhum bloqueio técnico identificado.

## Registro de mudanças

### 20/08/2026 — Migração iniciada para Tauri 2

- Auditados os projetos Unity, Ren'Py e o protótipo PySide/QML.
- Mantidos os três projetos existentes intactos como referência e recuperação.
- Criado `uat-desktop-tauri` com Tauri 2, Rust, React e TypeScript.
- Implementados layout, navegação, biblioteca persistente e seleção nativa de jogo.
- Implementada detecção Rust de Unity Mono/IL2CPP, x86/x64 e Ren'Py.
- Adicionada página de diagnóstico dos componentes legados.
- Build Vite/TypeScript, `cargo check` e testes Rust aprovados.
- Testes Unity aprovados: 16; um teste online opcional ignorado.
- Registrada em `ANALISE_TAURI.md` a necessidade de testes de caracterização do Ren'Py.

### 20/08/2026 — Planejamento

- Projetos transferidos para `C:\Users\Skell\Documents\Projeto`.
- Estrutura existente inspecionada.
- Stack técnica definida.
- Arquitetura modular e fases registradas em `PLANO_IMPLEMENTACAO.md`.
- Criado este arquivo de acompanhamento.

### 20/08/2026 — Fundação executável

- Criado o projeto `uat-desktop` com Python 3.11 e estrutura `src`.
- Criado ambiente virtual isolado com PySide6, HTTPX, pytest, pytest-qt, Ruff e uv.
- Gerado `uv.lock` com 20 pacotes resolvidos.
- Implementada interface QML com tema escuro, sidebar e sete páginas navegáveis.
- Implementada biblioteca vazia ligada a um modelo Qt real.
- Implementado banco SQLite com jogos, modelos, dependências e operações.
- Implementada seleção de executável pela interface.
- Implementada detecção inicial não destrutiva de Unity e Ren'Py.
- Implementada persistência do jogo e atualização imediata da biblioteca.
- Implementadas mensagens para jogo desconhecido, duplicado e cadastro concluído.
- Ruff executado sem erros.
- Seis testes automatizados aprovados, incluindo banco, detector e carregamento QML.

### 20/08/2026 — Revisão visual completa

- Removida a titlebar nativa separada do aplicativo.
- Implementada titlebar integrada, arrastável e com controles próprios.
- Adicionados minimizar, maximizar/restaurar e fechar.
- Mantido redimensionamento nativo pelas bordas da janela sem moldura.
- Substituídos glifos Unicode por ícones SVG locais e consistentes.
- Refeitas proporções, espaçamentos, superfícies e cores conforme o mockup.
- Recriada a tabela da biblioteca com cabeçalho de colunas.
- Adicionados badges de motor, indicador de estado e ações padronizadas.
- Jogos não instalados agora exibem a ação `Instalar`.
- Corrigido o conteúdo do botão `Adicionar jogo`.
- QML carregado com sucesso e janela sem moldura coberta por teste automatizado.

## Modelo para futuras atualizações

```text
### DD/MM/AAAA — Título

- Alterações realizadas.
- Testes executados e resultados.
- Decisões tomadas.
- Pendências ou bloqueios.
```
