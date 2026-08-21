# UAT Desktop — Plano de Implementação

## 1. Objetivo

Construir um aplicativo desktop único para configurar e executar tradução automática em jogos **Ren'Py** e **Unity**, mantendo adaptadores separados por motor e compartilhando modelos, biblioteca de jogos, downloads, diagnósticos e configurações.

O aplicativo deve funcionar em Windows sem Python instalado e reproduzir a experiência visual aprovada no mockup.

## 2. Stack definida

| Área | Tecnologia |
|---|---|
| Linguagem principal | Python 3.11 |
| Interface | PySide6 + Qt Quick/QML |
| Banco local | SQLite (`sqlite3`) |
| Modelos offline | Argos Translate + CTranslate2 |
| Processos externos | `QProcess` |
| Tarefas em segundo plano | Qt signals/slots + `QThreadPool` |
| Downloads | HTTPX executado em worker |
| Testes | pytest + pytest-qt |
| Qualidade | Ruff e type hints |
| Dependências | `pyproject.toml` + `uv.lock` |
| Build portátil | PyInstaller `onedir` |
| Instalador Windows | Inno Setup |
| Logs | `logging` + `RotatingFileHandler` |

## 3. Princípios arquiteturais

- O núcleo não deve depender da interface.
- Ren'Py e Unity serão adaptadores independentes.
- A interface não chamará scripts legados diretamente.
- Toda operação longa emitirá progresso e aceitará cancelamento seguro quando possível.
- Uma falha nunca substituirá uma configuração anteriormente funcional.
- Modelos serão armazenados uma única vez e compartilhados.
- Nenhum modelo será incluído no instalador base.
- O aplicativo não criará rotas indiretas de tradução sem decisão explícita.
- Os projetos atuais serão preservados até a nova aplicação alcançar paridade.

## 4. Estrutura planejada

```text
Projeto/
├── uat-desktop/
│   ├── pyproject.toml
│   ├── uv.lock
│   ├── src/uat_desktop/
│   │   ├── app.py
│   │   ├── domain/
│   │   │   ├── entities.py
│   │   │   ├── enums.py
│   │   │   └── results.py
│   │   ├── core/
│   │   │   ├── engine_detector.py
│   │   │   ├── model_manager.py
│   │   │   ├── download_manager.py
│   │   │   ├── process_manager.py
│   │   │   ├── diagnostics.py
│   │   │   └── backups.py
│   │   ├── adapters/
│   │   │   ├── base.py
│   │   │   ├── unity.py
│   │   │   └── renpy.py
│   │   ├── storage/
│   │   │   ├── database.py
│   │   │   ├── repositories.py
│   │   │   └── migrations/
│   │   ├── presentation/
│   │   │   ├── controllers/
│   │   │   ├── viewmodels/
│   │   │   └── qml/
│   │   │       ├── App.qml
│   │   │       ├── pages/
│   │   │       ├── components/
│   │   │       └── themes/
│   │   └── resources/
│   └── tests/
│       ├── unit/
│       ├── integration/
│       └── ui/
├── uat-renpy/
├── uat-unity/
├── PLANO_IMPLEMENTACAO.md
└── PROGRESSO.md
```

## 5. Dados locais

Por padrão:

```text
%LOCALAPPDATA%\UAT Desktop\
├── uat.db
├── models\
├── downloads\
├── logs\
├── backups\
└── temp\
```

O usuário poderá alterar a pasta central dos modelos. Uma futura versão portátil poderá usar uma pasta `data` ao lado do executável.

## 6. Modelo de dados inicial

### `games`

- ID interno.
- Nome e capa opcional.
- Pasta e executável.
- Motor detectado.
- Assinatura do executável para reconhecer jogos movidos.
- Datas de cadastro e última execução.

### `game_profiles`

- Jogo relacionado.
- Idioma original e destino.
- Provedor e modelo selecionados.
- Porta e preferências.
- Estado da configuração.

### `engine_installations`

- Jogo relacionado.
- Runtime e arquitetura.
- Componentes e versões instaladas.
- Data da última validação.

### `models`

- Par de idiomas, versão e caminho.
- Tamanho e integridade.
- Estado: disponível, instalando, instalado, incompleto ou corrompido.
- Último uso.

### `game_models`

- Relação entre jogos e modelos.
- Impede exclusão acidental de modelo em uso.

### `operations`, `diagnostics` e `backups`

- Histórico de downloads, instalações e reparos.
- Resultados dos diagnósticos.
- Arquivos alterados e instruções de restauração.

## 7. Telas da primeira versão

### Biblioteca

- Todos/Ren'Py/Unity.
- Busca de jogos.
- Estado, motor, par de idiomas e última execução.
- Jogar, instalar/configurar e menu de ações.

### Assistente

1. Selecionar pasta ou executável.
2. Detectar motor e detalhes técnicos.
3. Detectar/confirmar idioma original.
4. Escolher idioma de destino.
5. Verificar modelo direto e dependências.
6. Mostrar plano, tamanho e alterações.
7. Baixar, instalar e validar.
8. Salvar e iniciar.

### Modelos

- Catálogo, busca e filtros.
- Instalar, validar, reparar e excluir.
- Tamanho, versão, integridade e último uso.
- Jogos dependentes.

### Downloads

- Fila e progresso por etapa.
- Cancelamento, repetição e detalhes de falha.

### Diagnósticos

- Testes aprovados, alertas e erros.
- Correção sugerida.
- Logs técnicos expansíveis e exportáveis.

### Configurações

- Pasta de modelos e downloads.
- Porta padrão.
- Idioma e tema da interface.
- Logs e modo avançado.

### Detalhes de jogo

- Dados persistidos e estado atual.
- Painel específico Unity ou Ren'Py.
- Jogar, reconfigurar, reparar, diagnosticar e remover integração.

## 8. Contrato dos adaptadores

```python
class EngineAdapter(Protocol):
    def detect(self, path: Path) -> EngineDetection: ...
    def inspect(self, path: Path) -> GameInspection: ...
    def plan_install(self, profile: GameProfile) -> InstallationPlan: ...
    def install(self, plan: InstallationPlan, progress: ProgressSink) -> InstallationResult: ...
    def validate(self, profile: GameProfile) -> DiagnosticReport: ...
    def configure(self, profile: GameProfile) -> ConfigurationResult: ...
    def launch(self, profile: GameProfile) -> LaunchResult: ...
    def plan_uninstall(self, profile: GameProfile) -> UninstallPlan: ...
    def uninstall(self, plan: UninstallPlan) -> UninstallResult: ...
```

## 9. Migração dos projetos atuais

### Unity

Extrair gradualmente do `uat_unity.py`:

- Detecção de jogo, Mono/IL2CPP e arquitetura.
- Download, hash e extração segura.
- Instalação de BepInEx/XUnity.
- Configuração do XUnity.
- Detecção de idioma.
- Servidor local e diagnósticos.

### Ren'Py

Extrair gradualmente:

- Descoberta e instalação.
- Gerenciamento de idiomas e modelos.
- Servidor local e watchdog.
- Configurações de provedores.
- Cache e dicionário.
- Hooks moderno/legado permanecem como arquivos instalados no jogo.

Os CLIs serão convertidos em consumidores do novo núcleo até poderem ser aposentados ou mantidos como ferramentas avançadas.

## 10. Etapas de implementação

### Etapa 1 — Fundação

- Criar `uat-desktop` e configuração do projeto.
- Configurar PySide6, QML, pytest e Ruff.
- Criar janela base, tema e navegação.
- Criar banco SQLite e migração inicial.

**Entrega:** aplicativo vazio navegável, banco inicializado e testes básicos.

### Etapa 2 — Biblioteca

- Entidades e repositórios de jogos.
- Adicionar/remover jogo da biblioteca.
- Persistir e restaurar perfis.
- Implementar layout aprovado.

**Entrega:** biblioteca funcional com dados reais.

### Etapa 3 — Detecção e adaptadores

- Contrato comum.
- Adaptador Unity.
- Adaptador Ren'Py.
- Página de inspeção e diagnóstico inicial.

**Entrega:** selecionar jogo e identificar seu motor sem instalar nada.

### Etapa 4 — Modelos compartilhados

- Catálogo e cache Argos central.
- Download, validação e quarentena.
- Referências entre jogos e modelos.
- Tela de modelos.

**Entrega:** modelos gerenciados de forma independente dos jogos.

### Etapa 5 — Instalação Unity

- Plano de instalação.
- BepInEx/XUnity por runtime e arquitetura.
- Configuração, backup, validação e reparo.
- Iniciar servidor e jogo.

**Entrega:** fluxo Unity completo pela interface.

### Etapa 6 — Instalação Ren'Py

- Instalação dos hooks.
- Provedor, cache e dicionário.
- Servidor/watchdog e inicialização.
- Suporte moderno e legado.

**Entrega:** fluxo Ren'Py completo pela interface.

### Etapa 7 — Diagnósticos e robustez

- Logs visuais e exportação.
- Reparos guiados.
- Cancelamento e recuperação.
- Migração de configurações antigas.

**Entrega:** operação recuperável sem usar terminal.

### Etapa 8 — Distribuição

- PyInstaller `onedir`.
- ZIP portátil.
- Instalador Inno Setup.
- Teste em Windows limpo sem Python.

**Entrega:** versão candidata para clientes.

## 11. Estratégia de testes

- Testes unitários para regras do núcleo.
- Testes de contrato para os adaptadores.
- Testes de banco e migrações.
- Testes de UI com `pytest-qt`.
- Testes de integração com pastas de jogos simuladas.
- Matriz Unity: Mono/IL2CPP, x86/x64 e caminhos Unicode.
- Matriz Ren'Py: hooks moderno/legado, tags, variáveis e emojis.
- Modelos válidos, antigos, incompletos e corrompidos.
- Vários jogos usando o mesmo modelo.
- Downloads interrompidos e portas ocupadas.
- Build executado em Windows limpo sem Python.

## 12. Riscos e mitigação

| Risco | Mitigação |
|---|---|
| Duplicação das bibliotecas Argos | Um único runtime e cache central |
| Interface travar durante downloads | Workers, sinais Qt e cancelamento |
| Regressão nos tradutores atuais | Testes de caracterização antes da extração |
| Instalação quebrar o jogo | Plano, backup, validação e rollback |
| Caminhos Unicode | Testes dedicados e alias ASCII controlado |
| Modelo incompatível | Validação real antes de salvar o perfil |
| Pacote final muito grande | Modelos sob demanda e análise de dependências |
| Diferença Python 3.11/3.12 | Padronizar todo o novo aplicativo em Python 3.11 |

## 13. Critérios de conclusão da primeira versão

- Interface equivalente ao mockup aprovado.
- Biblioteca persiste e restaura jogos.
- Seleção identifica Ren'Py ou Unity.
- Unity identifica Mono/IL2CPP e x86/x64.
- Usuário escolhe idiomas e baixa modelo direto.
- Modelos são compartilhados e gerenciáveis.
- Instalação, reparo, diagnóstico e execução funcionam pela GUI.
- Configuração anterior é preservada em falhas.
- Aplicativo funciona sem Python instalado.
- Build passa pela matriz mínima de testes.

## 14. Ordem imediata

1. Criar o esqueleto `uat-desktop`.
2. Configurar Python 3.11, PySide6 e QML.
3. Implementar tema e janela principal do mockup.
4. Criar SQLite e entidades iniciais.
5. Implementar a biblioteca antes de migrar instalações.

