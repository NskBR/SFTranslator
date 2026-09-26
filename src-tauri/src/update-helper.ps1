param([Parameter(Mandatory = $true)][string]$ConfigPath)
$ErrorActionPreference = 'Stop'
$config = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json

try {
    if (-not (Test-Path -LiteralPath $config.installer -PathType Leaf)) {
        throw 'O instalador baixado não foi encontrado.'
    }
    $installerStream = [IO.File]::OpenRead($config.installer)
    $sha256 = [Security.Cryptography.SHA256]::Create()
    try {
        $actual = [BitConverter]::ToString($sha256.ComputeHash($installerStream)).Replace('-', '')
    } finally {
        $sha256.Dispose()
        $installerStream.Dispose()
    }
    if ($actual -ine $config.sha256) {
        throw 'O SHA-256 do instalador não confere com o release oficial.'
    }
    [IO.File]::WriteAllText($config.ready, 'ready')

    $deadline = [DateTime]::UtcNow.AddMinutes(3)
    while (-not (Test-Path -LiteralPath $config.go)) {
        if ([DateTime]::UtcNow -gt $deadline) { throw 'A atualização não foi autorizada pelo aplicativo.' }
        Start-Sleep -Milliseconds 200
    }
    while (Get-Process -Id $config.parent -ErrorAction SilentlyContinue) {
        if ([DateTime]::UtcNow -gt $deadline) { throw 'O aplicativo não fechou a tempo para instalar a atualização.' }
        Start-Sleep -Milliseconds 250
    }

    $arguments = '/S /UPDATE /D=' + $config.destination
    $installer = Start-Process -FilePath $config.installer -ArgumentList $arguments -WindowStyle Hidden -PassThru -Wait
    if ($installer.ExitCode -notin @(0, 3010)) {
        throw ('A instalação falhou (código ' + $installer.ExitCode + ').')
    }
    if (-not (Test-Path -LiteralPath $config.executable -PathType Leaf)) {
        throw 'A instalação terminou, mas o executável não foi encontrado.'
    }
    $null = Start-Process -FilePath $config.executable -PassThru
} catch {
    $message = $_.Exception.Message
    [IO.File]::WriteAllText($config.error, $message)
    [IO.File]::WriteAllText($config.lastError, $message)
    if (-not (Get-Process -Id $config.parent -ErrorAction SilentlyContinue) -and
        (Test-Path -LiteralPath $config.executable -PathType Leaf)) {
        $null = Start-Process -FilePath $config.executable -PassThru
    }
    exit 1
}
