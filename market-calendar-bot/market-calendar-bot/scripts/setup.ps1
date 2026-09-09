$ErrorActionPreference = 'Stop'
$Project = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $Project
$Launcher = Get-Command py -ErrorAction SilentlyContinue
if ($Launcher) {
    & $Launcher.Source -3 -m venv .venv
} else {
    $Python = Get-Command python -ErrorAction SilentlyContinue
    $PythonPath = if ($Python) { $Python.Source } else { $null }
    if (-not $Python) {
        $Bundled = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
        if (Test-Path -LiteralPath $Bundled) { $PythonPath = $Bundled }
    }
    if (-not $PythonPath) { throw 'Python 3.12 이상을 설치한 뒤 다시 실행하세요.' }
    & $PythonPath -m venv .venv
}
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
if (-not (Test-Path -LiteralPath '.env')) {
    Copy-Item -LiteralPath '.env.example' -Destination '.env'
}
Write-Host '설치 완료. .env에 새 일정봇 토큰을 입력하세요.'
