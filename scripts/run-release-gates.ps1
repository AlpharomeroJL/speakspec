# Run all Speakspec release gates locally.
$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $RepoRoot "sidecar\.venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    throw "sidecar venv not found. Run dev setup from CONTRIBUTING.md first."
}

function Invoke-Gate([string]$Name, [scriptblock]$Block) {
    Write-Host "==> $Name"
    & $Block
    if ($LASTEXITCODE -ne 0) { throw "$Name failed with exit code $LASTEXITCODE" }
}

Push-Location $RepoRoot
try {
    Invoke-Gate "pytest" { & $Python -m pytest sidecar/tests -q }
    Invoke-Gate "mermaid corpus gate" { & $Python sidecar/tests/run_mermaid_corpus.py }
    Invoke-Gate "AGENTS.md gate" { & $Python sidecar/tests/run_agents_gate.py }
    Invoke-Gate "template gate" { & $Python sidecar/tests/run_template_check.py }
    Invoke-Gate "ASR sample" { powershell -ExecutionPolicy Bypass -File sidecar/tests/gen_tts_sample.ps1 }
    Invoke-Gate "ASR gate" { & $Python sidecar/tests/run_asr_check.py }
    Write-Host "==> All release gates passed"
} finally {
    Pop-Location
}
