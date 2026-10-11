param([switch]$SeedDemo)
$ErrorActionPreference = 'Stop'
$projectPath = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectPath
if (-not (Test-Path '.venv/Scripts/python.exe')) { python -m venv .venv }
& ./.venv/Scripts/python.exe -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed.' }
$portableNodePath = Join-Path $projectPath '.tools/node-v22.22.0-win-x64'
if (Test-Path $portableNodePath) { $env:Path = "$portableNodePath;$env:Path" }
Push-Location frontend
try {
    npm.cmd ci
    if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed.' }
    npm.cmd run build
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
} finally { Pop-Location }
if ($SeedDemo) {
    & ./.venv/Scripts/python.exe -m backend.seed
    if ($LASTEXITCODE -ne 0) { throw 'Demo seed failed.' }
}
& ./.venv/Scripts/python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
