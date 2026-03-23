param(
    [string]$BindAddress = "127.0.0.1",
    [int]$Port = 8765
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

function Get-AvailablePort {
    param(
        [int]$RequestedPort,
        [int]$MaxOffset = 20
    )

    for ($candidate = $RequestedPort; $candidate -le ($RequestedPort + $MaxOffset); $candidate++) {
        $listeners = Get-NetTCPConnection -State Listen -LocalPort $candidate -ErrorAction SilentlyContinue
        if (-not $listeners) {
            return $candidate
        }
    }

    throw "No free port was found between $RequestedPort and $($RequestedPort + $MaxOffset)."
}

$pythonCommand = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCommand) {
    Write-Error "Python was not found. Please install Python 3 and try again."
    exit 1
}

$actualPort = Get-AvailablePort -RequestedPort $Port
if ($actualPort -ne $Port) {
    Write-Warning "Port $Port is already occupied. The launcher switched to port $actualPort."
}

Write-Host "Starting GitHub push tool..."
Write-Host "URL: http://$BindAddress`:$actualPort"
Write-Host ""

& $pythonCommand.Source (Join-Path $scriptDir "app.py") --host $BindAddress --port $actualPort
exit $LASTEXITCODE
