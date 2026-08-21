$ErrorActionPreference = "Stop"

$projectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$releaseDirectory = Join-Path $projectRoot "release"

Push-Location $projectRoot
try {
    & npm.cmd run tauri -- build
    if ($LASTEXITCODE -ne 0) {
        throw "A geração do pacote Tauri falhou (código $LASTEXITCODE)."
    }

    New-Item -ItemType Directory -Force -Path $releaseDirectory | Out-Null
    $artifacts = Get-ChildItem -Path (Join-Path $projectRoot "src-tauri\target\release\bundle") -Recurse -File |
        Where-Object { $_.Extension -in ".exe", ".msi", ".dmg", ".appimage", ".deb", ".rpm" }

    if (-not $artifacts) {
        throw "Nenhum instalador foi encontrado após o build."
    }

    $artifacts | Copy-Item -Destination $releaseDirectory -Force
    Write-Host "Release pronta em: $releaseDirectory"
    $artifacts | ForEach-Object { Write-Host " - $($_.Name)" }
}
finally {
    Pop-Location
}
