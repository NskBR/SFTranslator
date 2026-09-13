# SFTranslator

Aplicativo Windows para tradução local de jogos Unity e Ren'Py.

Todo o código, adaptadores, ferramentas de build e documentação estão em [`uat-desktop-tauri`](uat-desktop-tauri/README.md).

```powershell
cd uat-desktop-tauri
npm install
npm run runtimes
npm run tauri dev
```

Para gerar o instalador completo: `npm run release` nessa mesma pasta. O ambiente Python de build é criado em `uat-desktop-tauri/.venv`; o usuário final não precisa instalar Python ou LibreTranslate.
