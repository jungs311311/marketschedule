$ErrorActionPreference = 'Stop'
Unregister-ScheduledTask -TaskName 'Telegram Market Calendar Bot' -Confirm:$false
Write-Host '작업 스케줄러 등록만 제거했습니다. 코드·설정·DB는 남아 있습니다.'
