param(
    [string]$TaskName = "MacroDashboard-DailyUpdateDispatch"
)

$ErrorActionPreference = "Stop"
$dispatcher = Join-Path $PSScriptRoot "dispatch_daily_update.ps1"
if (-not (Test-Path -LiteralPath $dispatcher)) { throw "Dispatcher script not found: $dispatcher" }

$userId = "$env:USERDOMAIN\$env:USERNAME"
$arguments = "-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$dispatcher`""
$action = New-ScheduledTaskAction -Execute "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -Argument $arguments
$triggers = @(
    New-ScheduledTaskTrigger -AtLogOn -User $userId
    New-ScheduledTaskTrigger -Daily -At "09:30"
)
$principal = New-ScheduledTaskPrincipal -UserId $userId -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -RestartCount 2 -RestartInterval (New-TimeSpan -Minutes 5) -ExecutionTimeLimit (New-TimeSpan -Minutes 10) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $triggers -Principal $principal -Settings $settings -Description "Fallback: dispatch the daily macro-dashboard update only when GitHub scheduling has not produced a run." -Force | Out-Null
Get-ScheduledTask -TaskName $TaskName | Select-Object TaskName, State, TaskPath
