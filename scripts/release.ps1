$ErrorActionPreference = "Stop"

$projectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$releaseDirectory = Join-Path $projectRoot "release"
$previousCargoTarget = $env:CARGO_TARGET_DIR
$buildTarget = if ($previousCargoTarget) { $previousCargoTarget } else { Join-Path $env:LOCALAPPDATA "SFTranslator\build-target" }
New-Item -ItemType Directory -Force -Path $buildTarget | Out-Null
$env:CARGO_TARGET_DIR = $buildTarget

Push-Location $projectRoot
try {
    $npmVersion = (Get-Content -LiteralPath (Join-Path $projectRoot "package.json") -Raw | ConvertFrom-Json).version
    $tauriVersion = (Get-Content -LiteralPath (Join-Path $projectRoot "src-tauri\tauri.conf.json") -Raw | ConvertFrom-Json).version
    $cargoVersion = [regex]::Match((Get-Content -LiteralPath (Join-Path $projectRoot "src-tauri\Cargo.toml") -Raw), '(?m)^version\s*=\s*"([^"]+)"').Groups[1].Value
    if ($npmVersion -ne $tauriVersion -or $npmVersion -ne $cargoVersion) {
        throw "As versões de package.json ($npmVersion), tauri.conf.json ($tauriVersion) e Cargo.toml ($cargoVersion) precisam ser iguais."
    }

    & (Join-Path $PSScriptRoot "prepare-runtimes.ps1")
    & npm.cmd run tauri -- build
    if ($LASTEXITCODE -ne 0) {
        throw "A geração do pacote Tauri falhou (código $LASTEXITCODE)."
    }

    New-Item -ItemType Directory -Force -Path $releaseDirectory | Out-Null
    $artifacts = @(Get-ChildItem -Path (Join-Path $buildTarget "release\bundle\nsis") -File |
        Where-Object { $_.Name -eq "SFTranslator_${npmVersion}_x64-setup.exe" })

    if (-not $artifacts) {
        throw "O instalador NSIS SFTranslator_${npmVersion}_x64-setup.exe não foi encontrado após o build."
    }

    $artifacts | Copy-Item -Destination $releaseDirectory -Force
    $installerPath = Join-Path $releaseDirectory $artifacts[0].Name
    $installerStream = [IO.File]::OpenRead($installerPath)
    $sha256 = [Security.Cryptography.SHA256]::Create()
    try {
        $hash = [BitConverter]::ToString($sha256.ComputeHash($installerStream)).Replace('-', '').ToLowerInvariant()
    }
    finally {
        $sha256.Dispose()
        $installerStream.Dispose()
    }
    Set-Content -LiteralPath (Join-Path $releaseDirectory "SHA256SUMS.txt") -Value "$hash  $($artifacts[0].Name)" -Encoding ASCII
    Write-Host "Release pronta em: $releaseDirectory"
    Write-Host " - $($artifacts[0].Name) (SHA-256: $hash)"
}
finally {
    $env:CARGO_TARGET_DIR = $previousCargoTarget
    Pop-Location
}
