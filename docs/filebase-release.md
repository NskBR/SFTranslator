# Publicar o SFTranslator no Filebase

1. Altere a versão do desktop em `package.json` e rode `Build.bat`. O build
   sincroniza a versão e gera o setup NSIS em `release/`.
2. Escreva as notas em `docs/release-notes/<versão>.txt`, em UTF-8.
3. Preencha as duas chaves no `enviar-filebase.bat` local, ignorado pelo Git.
   Execute `enviar-filebase.bat -DryRun` para conferir os destinos.
4. Execute `enviar-filebase.bat` e digite `PUBLICAR`.

O publicador envia um setup para `sfs/sftranslator-updates/releases/<versão>/`
e, quando há notas, um `patch-notes.txt` na mesma pasta. Ele verifica o tamanho
e o SHA-256 pelo Worker antes de promover o `latest.json`. O manifesto inclui
as notas que aparecem no aplicativo.

No Worker `sftranslator-updates`, configure `FILEBASE_BUCKET` como texto com
valor `sfs` e cadastre `FILEBASE_ACCESS_KEY_ID` e
`FILEBASE_SECRET_ACCESS_KEY` como secrets de produção.

As versões distribuídas antes da migração consultam o GitHub. O primeiro
instalador com a migração precisa chegar a esses usuários pelo canal antigo
ou ser instalado manualmente.
