param([switch]$DryRun)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$config = Get-Content -Raw (Join-Path $PSScriptRoot 'filebase-distribution.json') | ConvertFrom-Json
$version = (Get-Content -Raw (Join-Path $root 'package.json') | ConvertFrom-Json).version
if ($version -cnotmatch '^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$') { throw 'Versao de desktop invalida.' }
$bucket = $config.bucket
if ($bucket -cnotmatch '^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$') { throw 'Bucket invalido em filebase-distribution.json.' }
$name = 'SFTranslator-Windows-x64-setup.exe'
$installer = Get-Item -LiteralPath (Join-Path $root "release/SFTranslator_$($version)_x64-setup.exe")
function Get-Sha256($file) {
    $stream = [IO.File]::OpenRead($file)
    $algorithm = [Security.Cryptography.SHA256]::Create()
    try { [BitConverter]::ToString($algorithm.ComputeHash($stream)).Replace('-', '').ToLowerInvariant() }
    finally { $algorithm.Dispose(); $stream.Dispose() }
}
$hash = Get-Sha256 $installer.FullName
$key = "$($config.prefix)/releases/$version"
$url = "$($config.publicBaseUrl)/$($config.publicPrefix)/releases/$version/$name"
$notesPath = Join-Path $root "docs/release-notes/$version.txt"
$notes = if (Test-Path -LiteralPath $notesPath -PathType Leaf) {
    [IO.File]::ReadAllText($notesPath).Trim()
} else { '' }
$manifest = [ordered]@{ app = 'SFTranslator'; platform = 'windows-x64'; version = $version; file = $name; url = $url; size = $installer.Length; sha256 = $hash; notes = $notes }
$manifestJson = $manifest | ConvertTo-Json
$utf8 = [Text.UTF8Encoding]::new($false)
if ($utf8.GetByteCount($manifestJson) -gt 65536) { throw 'O manifesto excede 64 KiB. Reduza as notas da versao.' }
Write-Host "SFTranslator $version -> s3://$bucket/$key"
Write-Host "Setup: s3://$bucket/$key/$name"
if ($notes) { Write-Host "Notas: s3://$bucket/$key/patch-notes.txt" }
Write-Host "Manifesto: s3://$bucket/$($config.prefix)/latest.json"
if ($DryRun) { $manifestJson; return }
if (!$env:FILEBASE_ACCESS_KEY_ID -or !$env:FILEBASE_SECRET_ACCESS_KEY) {
    throw 'Preencha FILEBASE_ACCESS_KEY_ID e FILEBASE_SECRET_ACCESS_KEY no enviar-filebase.bat.'
}
if ((Read-Host 'Digite PUBLICAR para confirmar') -cne 'PUBLICAR') { throw 'Publicacao cancelada.' }
$aws = (Get-Command aws.exe -ErrorAction Stop).Source
$temp = Join-Path ([IO.Path]::GetTempPath()) ('sftranslator-publish-' + [guid]::NewGuid())
New-Item -ItemType Directory -Path $temp | Out-Null
function Invoke-S3 {
    & $aws --no-cli-pager --region $config.region --endpoint-url $config.endpoint @args
    if ($LASTEXITCODE -ne 0) { throw "Filebase retornou erro ($LASTEXITCODE)." }
}
function Upload($file, $objectKey, $cache, $type) {
    Invoke-S3 s3 cp $file "s3://$bucket/$objectKey" --cache-control $cache --content-type $type
}
function Assert-PublicHash($address, $expected, $size) {
    $download = Join-Path $temp 'verification.bin'
    & curl.exe --fail --progress-bar --show-error --retry 3 --output $download $address
    if ($LASTEXITCODE -ne 0) { throw "Falha ao baixar $address." }
    Write-Host 'Conferindo tamanho e SHA-256...'
    if ((Get-Item -LiteralPath $download).Length -ne $size -or (Get-Sha256 $download) -ne $expected) {
        throw "Tamanho ou SHA-256 divergente em $address."
    }
}
$previous = @{}
try {
    foreach ($variable in 'AWS_ACCESS_KEY_ID','AWS_SECRET_ACCESS_KEY','AWS_SESSION_TOKEN') {
        $previous[$variable] = [Environment]::GetEnvironmentVariable($variable)
    }
    $env:AWS_ACCESS_KEY_ID = $env:FILEBASE_ACCESS_KEY_ID
    $env:AWS_SECRET_ACCESS_KEY = $env:FILEBASE_SECRET_ACCESS_KEY
    $env:AWS_SESSION_TOKEN = $null
    Write-Host '[1/5] Consultando a versao no Filebase...'
    $existing = Invoke-S3 s3api list-objects-v2 --bucket $bucket --prefix "$key/" --max-items 1 --output json | ConvertFrom-Json
    if ($existing.Contents) { throw "A versao $version ja existe no Filebase. Use uma nova versao." }
    $jsonPath = Join-Path $temp 'latest.json'
    [IO.File]::WriteAllText($jsonPath, $manifestJson, $utf8)
    $immutable = 'public,max-age=31536000,immutable'
    Write-Host '[2/5] Enviando o instalador...'
    Upload $installer.FullName "$key/$name" $immutable 'application/octet-stream'
    Write-Host '[3/5] Baixando o instalador pelo Worker para verificar a integridade...'
    Assert-PublicHash $url $hash $installer.Length
    $jsonHash = Get-Sha256 $jsonPath
    $jsonSize = (Get-Item -LiteralPath $jsonPath).Length
    Write-Host '[4/5] Publicando as notas da versao e o latest.json...'
    if ($notes) {
        $patchNotesPath = Join-Path $temp 'patch-notes.txt'
        [IO.File]::WriteAllText($patchNotesPath, $notes, $utf8)
        Upload $patchNotesPath "$key/patch-notes.txt" $immutable 'text/plain; charset=utf-8'
    }
    Upload $jsonPath "$($config.prefix)/latest.json" 'no-store' 'application/json'
    Write-Host '[5/5] Verificando o manifesto publicado...'
    Assert-PublicHash "$($config.publicBaseUrl)/$($config.publicPrefix)/latest.json" $jsonHash $jsonSize
    Write-Host "Manifesto e instalador $version verificados pelo Worker."
} finally {
    foreach ($variable in $previous.Keys) { [Environment]::SetEnvironmentVariable($variable, $previous[$variable]) }
    foreach ($file in 'latest.json','patch-notes.txt','verification.bin') {
        $path = Join-Path $temp $file
        if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path }
    }
    Remove-Item -LiteralPath $temp
}
