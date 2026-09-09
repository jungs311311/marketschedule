$ErrorActionPreference = 'Stop'
$Utf8 = New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding = $Utf8
[Console]::OutputEncoding = $Utf8
$OutputEncoding = $Utf8
$Project = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Project '.venv\Scripts\python.exe'
$EnvFile = Join-Path $Project '.env'
Set-Location -LiteralPath $Project
$env:PYTHONUTF8 = '1'

if (-not (Test-Path -LiteralPath $Python)) {
    throw '설치 환경이 없습니다. scripts\setup.ps1을 먼저 실행하세요.'
}

Write-Host ''
Write-Host '1/4 BotFather가 준 새 일정봇 토큰을 입력하세요.' -ForegroundColor Cyan
Write-Host '입력한 글자는 화면에 표시되지 않습니다.'
$SecureToken = Read-Host 'Bot token' -AsSecureString
$Pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecureToken)
try {
    $Token = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($Pointer)
} finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($Pointer)
}
if ($Token -notmatch '^\d+:[A-Za-z0-9_-]{20,}$') {
    throw '토큰 형식이 올바르지 않습니다. BotFather 메시지의 HTTP API token을 사용하세요.'
}

$Content = Get-Content -LiteralPath $EnvFile -Encoding UTF8
$Content = $Content -replace '^MARKET_BOT_TOKEN=.*$', ('MARKET_BOT_TOKEN=' + $Token)
Set-Content -LiteralPath $EnvFile -Value $Content -Encoding UTF8
$Token = $null
Write-Host ''
Write-Host '2/4 토큰으로 연결할 봇을 확인합니다.' -ForegroundColor Cyan
$BotName = (& $Python -m marketbot bot-info).Trim()
Write-Host "확인된 봇: $BotName" -ForegroundColor Green

for ($Attempt = 1; $Attempt -le 3; $Attempt++) {
    Write-Host ''
    Write-Host "3/4 텔레그램에서 $BotName 채팅을 열고 /start를 보내세요." -ForegroundColor Cyan
    Read-Host '/start를 보냈으면 Enter'
    $Rows = @(& $Python -m marketbot chat-id | Where-Object { $_ -match '^-?\d+\t' })
    if ($Rows.Count -gt 0) { break }
    Write-Host '아직 /start 메시지를 찾지 못했습니다.' -ForegroundColor Yellow
}
if ($Rows.Count -eq 0) {
    throw '/start를 확인하지 못했습니다. 봇 채팅이 맞는지 확인하고 다시 실행하세요.'
}

if ($Rows.Count -eq 1) {
    $ChatId = ($Rows[0] -split "\t", 2)[0]
} else {
    Write-Host '확인된 채팅:'
    $Rows | ForEach-Object { Write-Host $_ }
    $ChatId = Read-Host '사용할 CHAT_ID 숫자'
}
if ($ChatId -notmatch '^-?\d+$') { throw 'CHAT_ID는 숫자여야 합니다.' }
$Content = Get-Content -LiteralPath $EnvFile -Encoding UTF8
$Content = $Content -replace '^MARKET_BOT_CHAT_ID=.*$', ('MARKET_BOT_CHAT_ID=' + $ChatId)
Set-Content -LiteralPath $EnvFile -Value $Content -Encoding UTF8

Write-Host ''
Write-Host '4/4 연결 확인 메시지를 발송합니다.' -ForegroundColor Cyan
& $Python -m marketbot test-message
Write-Host ''
Write-Host '연결 완료. 텔레그램에서 [연결 확인] 메시지를 확인하세요.' -ForegroundColor Green
Write-Host '자동 알림을 시작하려면 INSTALL-AUTORUN.cmd를 실행하세요.'
