# Análise e migração para Tauri 2

## Resultado da auditoria

- **UAT Unity:** código-fonte, instalador, middleware, DLL do XUnity, builds e cache de componentes presentes. A suíte local passou em 16 testes; o único teste ignorado exige acesso online aos pacotes oficiais.
- **UAT Ren'Py:** hooks moderno e legado, instalador, servidor local, executável portátil e modelo Argos presentes. Não existe uma suíte automatizada equivalente à do Unity, portanto o conteúdo parece completo, mas ainda precisa de testes de caracterização antes da migração.
- **App PySide/QML:** chegou à fundação e biblioteca inicial. A integração real dos motores ainda não foi feita. O ambiente virtual também referencia um Python 3.11 que não existe nesta máquina.

## Decisão

A nova aplicação está em `uat-desktop-tauri`. O app QML e os dois motores foram mantidos intactos para comparação e recuperação.

## O que já funciona no Tauri

- Interface React responsiva, janela sem moldura e navegação completa.
- Seletor nativo de executável.
- Detecção Rust de Unity, Mono/IL2CPP, x86/x64 e Ren'Py.
- Biblioteca persistente com gravação atômica em JSON no diretório de dados da aplicação.
- Diagnóstico do conteúdo legado em ambiente de desenvolvimento.

## Próximo marco

Criar testes de caracterização do Ren'Py e extrair operações dos scripts legados para comandos controlados pelo backend, começando por planos de instalação somente leitura, backup e validação.
