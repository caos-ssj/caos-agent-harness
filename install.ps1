<#
.SYNOPSIS
Instalador rápido de CAOS Agent Harness para Windows (PowerShell).

.DESCRIPTION
Crea .venv local con Python 3.11+, instala `caos-agent-harness` en modo editable
(la interfaz web ya viene precompilada, así que no necesitas Node.js salvo que
compiles la app de escritorio con `-Desktop`).

.EXAMPLE
.\install.ps1
.\install.ps1 -Dev -Serve
.\install.ps1 -Desktop
#>
[CmdletBinding()]
param(
    [switch]$Dev,
    [switch]$Desktop,
    [switch]$Serve
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Find-Python311 {
    foreach ($candidate in @(@("py", "-3.13"), @("py", "-3.12"), @("py", "-3.11"), @("py", "-3"), @("python", ""), @("python3", ""))) {
        $exe = $candidate[0]
        $arg = $candidate[1]
        if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) { continue }
        try {
            $verArgs = if ($arg) { @($arg, "-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')") } else { @("-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')") }
            $ver = (& $exe @verArgs 2>$null | Select-Object -First 1).Trim()
            if ($ver -match '^(\d+)\.(\d+)$' -and ([int]$Matches[1] -gt 3 -or ([int]$Matches[1] -eq 3 -and [int]$Matches[2] -ge 11))) {
                return @{ Exe = $exe; Arg = $arg; Version = $ver }
            }
        } catch {}
    }
    throw "Se requiere Python 3.11 o superior. Instálalo con: winget install Python.Python.3.12"
}

$py = Find-Python311
Write-Host "Usando Python $($py.Version) ($($py.Exe) $($py.Arg))" -ForegroundColor Cyan

$venvPy = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$venvHarness = Join-Path $PSScriptRoot ".venv\Scripts\caos-harness.exe"

if (-not (Test-Path $venvPy)) {
    Write-Host "Creando entorno virtual en .venv..."
    if ($py.Arg) {
        & $py.Exe $py.Arg -m venv .venv
    } else {
        & $py.Exe -m venv .venv
    }
}

Write-Host "Instalando caos-agent-harness..."
& $venvPy -m pip install --upgrade pip --quiet
$spec = if ($Dev) { ".[dev]" } else { "." }
& $venvPy -m pip install -e $spec

Write-Host ""
Write-Host "Comprobando herramientas detectadas en el sistema:" -ForegroundColor Cyan
& $venvPy -m caos_harness doctor --json | Out-Null

if ($Desktop) {
    foreach ($tool in @("node", "npm", "cargo")) {
        if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
            throw "Para compilar la app de escritorio en Windows se requiere '$tool' en PATH (Node.js 20+ y Rustup + MSVC Build Tools)."
        }
    }
    Write-Host "Instalando dependencias frontend y compilando CAOS Desktop (Tauri)..." -ForegroundColor Cyan
    Push-Location (Join-Path $PSScriptRoot "web")
    try {
        npm ci
        npm run build
    } finally {
        Pop-Location
    }
    & (Join-Path $PSScriptRoot "web\node_modules\.bin\tauri.cmd") build
    Write-Host "Instalador generado en: src-tauri\target\release\bundle\" -ForegroundColor Green
}

Write-Host ""
Write-Host "Listo para trabajar." -ForegroundColor Green
Write-Host "  Abrir dashboard web en este repo:  .\.venv\Scripts\caos-harness.exe serve"
Write-Host "  Inicializar cualquier otro repo:   cd C:\ruta\tu-proyecto; `"$venvHarness`" init --detect; `"$venvHarness`" serve"
if ($Serve) {
    & $venvHarness serve
}
