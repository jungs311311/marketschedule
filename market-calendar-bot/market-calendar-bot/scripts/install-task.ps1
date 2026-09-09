$ErrorActionPreference = 'Stop'
$Project = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Project '.venv\Scripts\pythonw.exe'
if (-not (Test-Path -LiteralPath $Python)) { throw '먼저 scripts\setup.ps1을 실행하세요.' }
$Action = New-ScheduledTaskAction -Execute $Python -Argument '-m marketbot --env .env run' -WorkingDirectory $Project
$Trigger = New-ScheduledTaskTrigger -AtLogOn
$Settings = New-ScheduledTaskSettingsSet -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 2) -ExecutionTimeLimit ([TimeSpan]::Zero) -StartWhenAvailable
Register-ScheduledTask -TaskName 'TelegramMarketCalendarBot' -Action $Action -Trigger $Trigger -Settings $Settings -Description '한국시간 오전 8시/오후 9시 증시 일정 알림' -Force
Start-ScheduledTask -TaskName 'TelegramMarketCalendarBot'
Write-Host 'Windows 예약 작업 TelegramMarketCalendarBot을 설치하고 시작했습니다.'
