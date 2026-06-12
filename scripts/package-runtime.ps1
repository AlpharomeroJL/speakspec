# Package the Speakspec runtime for Tauri release builds.
# Output: src-tauri/resources/speakspec-runtime/
param(
    [string]$NodeVersion = "22.14.0"
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$OutRoot = Join-Path $RepoRoot "src-tauri\resources\speakspec-runtime"
$SidecarSrc = Join-Path $RepoRoot "sidecar"
$VenvDir = Join-Path $OutRoot "sidecar\.venv"
$Python = Join-Path $VenvDir "Scripts\python.exe"

Write-Host "==> Packaging Speakspec runtime to $OutRoot"

if (Test-Path $OutRoot) {
    Remove-Item -Recurse -Force $OutRoot
}
New-Item -ItemType Directory -Force -Path $OutRoot | Out-Null

# --- Python venv (runtime deps only) ---
Write-Host "==> Creating Python venv"
$sysPython = Get-Command python -ErrorAction SilentlyContinue
if (-not $sysPython) {
    throw "python not found on PATH; install Python 3.11+ to package the runtime"
}
& python -m venv $VenvDir
& $Python -m pip install --upgrade pip wheel
& $Python -m pip install -r (Join-Path $SidecarSrc "requirements.txt")
Write-Host "==> Skipping NVIDIA wheels (installer size); GPU ASR uses CPU fallback unless wheels present"

# Install sidecar package (source copied below)
$SidecarDest = Join-Path $OutRoot "sidecar"
New-Item -ItemType Directory -Force -Path $SidecarDest | Out-Null
Copy-Item -Recurse -Force (Join-Path $SidecarSrc "speakspec") (Join-Path $SidecarDest "speakspec")
Copy-Item -Force (Join-Path $SidecarSrc "pyproject.toml") $SidecarDest
& $Python -m pip install -e $SidecarDest --no-deps

# --- Data files the sidecar reads at runtime ---
foreach ($rel in @("templates", "config", "dicts")) {
    Copy-Item -Recurse -Force (Join-Path $RepoRoot $rel) (Join-Path $OutRoot $rel)
}
$schemasDest = Join-Path $OutRoot "docs\schemas"
New-Item -ItemType Directory -Force -Path $schemasDest | Out-Null
Copy-Item -Force (Join-Path $RepoRoot "docs\schemas\*") $schemasDest

# --- Mermaid validator (Node) ---
$MermaidDir = Join-Path $OutRoot "tools\mermaid-validate"
Copy-Item -Recurse -Force (Join-Path $RepoRoot "tools\mermaid-validate") $MermaidDir
$env:CI = 'true'
$env:CI = 'true'
Push-Location $MermaidDir
if (Test-Path node_modules) { cmd /c 'rd /s /q node_modules' }
npm install --omit=dev --no-fund --no-audit
Pop-Location

# Portable node.exe for the validator
$NodeDir = Join-Path $OutRoot "node"
New-Item -ItemType Directory -Force -Path $NodeDir | Out-Null
$NodeZip = Join-Path $env:TEMP "node-v$NodeVersion-win-x64.zip"
$NodeUrl = "https://nodejs.org/dist/v$NodeVersion/node-v$NodeVersion-win-x64.zip"
if (-not (Test-Path $NodeZip)) {
    Write-Host "==> Downloading Node v$NodeVersion"
    Invoke-WebRequest -Uri $NodeUrl -OutFile $NodeZip -UseBasicParsing
}
$NodeExtract = Join-Path $env:TEMP "node-v$NodeVersion-win-x64"
if (-not (Test-Path $NodeExtract)) {
    Expand-Archive -Path $NodeZip -DestinationPath $env:TEMP -Force
}
Copy-Item -Force (Join-Path $NodeExtract "node.exe") (Join-Path $NodeDir "node.exe")

# Size report
$sizeMb = [math]::Round((Get-ChildItem -Recurse $OutRoot | Measure-Object -Property Length -Sum).Sum / 1MB, 1)
Write-Host "==> Runtime packaged: ${sizeMb} MB at $OutRoot"
if ($sizeMb -gt 130) {
    Write-Warning "Runtime exceeds 130 MB - verify installer stays under 120 MB after NSIS compression"
}
