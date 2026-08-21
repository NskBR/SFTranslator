# SFTranslator — Tauri 2

Nova interface unificada para os tradutores UAT Ren'Py e UAT Unity.

## Desenvolvimento

```powershell
npm install
npm run tauri dev
```

O backend Rust já detecta jogos Unity (Mono/IL2CPP e arquitetura) e Ren'Py, e persiste a biblioteca no diretório de dados da aplicação. Os motores Python legados permanecem intactos nas pastas vizinhas enquanto seus fluxos são migrados e testados.
