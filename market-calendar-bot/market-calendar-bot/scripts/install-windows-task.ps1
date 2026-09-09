$ErrorActionPreference = 'Stop'
$Project = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Project '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $Python)) {
    throw '먼저 scripts\setup.ps1을 실행하세요.'
}
$Action = New-ScheduledTaskAction -Execute $Python -Argument '-m marketbot run' -WorkingDirectory $Project
$Trigger = New-ScheduledTaskTrigger -AtLogOn
$Settings = New-ScheduledTaskSettingsSet -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask -TaskName 'Telegram Market Calendar Bot' -Action $Action -Trigger $Trigger -Settings $Settings -Description '한국시간 오전 8시·오후 9시 증시 일정 알림' -Force | Out-Null
Start-ScheduledTask -TaskName 'Telegram Market Calendar Bot'
Write-Host 'Windows 작업 스케줄러에 등록했습니다. 로그: data\marketbot.log'
