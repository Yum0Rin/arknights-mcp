# 注册 / 注销「方舟·每周刷新计划」Windows 计划任务
#
#   每周日 20:00 跑 scripts/weekly-refresh/weekly_refresh.py：
#     · 重新生成**下周**计划（plan_week.py → scheduling/data/weekly_plan.json）
#       —— 周日跑时用「明天(下周一)」算所属周 → range = 下周一..下周日（满 7 天），
#          与原先「周一早上跑」等价；代价是**今天(周日)不在本计划内**（周日日常先跑完再刷新）。
#     · 弹提示：计划窗口/预算/逐日 + 理智药读数是否过期（过期就提醒开游戏重测）
#   「错过的启动」= 开机后尽快补跑（-StartWhenAvailable）：周日没开电脑，开机后自动补。
#
# 用法（普通 PowerShell 即可，无需管理员——写仓库 + 弹自己会话的窗）：
#   powershell -ExecutionPolicy Bypass -File scripts\weekly-refresh\install_task.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\weekly-refresh\install_task.ps1 -Uninstall
#   powershell -ExecutionPolicy Bypass -File scripts\weekly-refresh\install_task.ps1 -Day Sunday -At 20:00
param(
    [switch]$Uninstall,
    [ValidateSet('Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday')]
    [string]$Day = 'Sunday',
    [string]$At = '20:00'
)

$ErrorActionPreference = 'Stop'
$TaskName = '方舟·每周刷新计划'

if ($Uninstall) {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Output "已注销计划任务：$TaskName"
    } else {
        Write-Output "没有找到计划任务：$TaskName（无需注销）"
    }
    return
}

$Repo   = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$Script = Join-Path $Repo 'scripts\weekly-refresh\weekly_refresh.py'
$Py     = 'C:\Python314\pythonw.exe'

if (-not (Test-Path $Script)) { throw "找不到脚本：$Script" }
if (-not (Test-Path $Py))     { throw "找不到 pythonw：$Py（按 AGENTS.md，Python 在 C:\Python314）" }

$action  = New-ScheduledTaskAction -Execute $Py -Argument ('"' + $Script + '"') -WorkingDirectory $Repo
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $Day -At $At
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 15) `
    -MultipleInstances IgnoreNew

$desc = '每周刷新一键长草计划：重生成 weekly_plan.json（今天..本周日）+ 弹窗提醒重测理智药。不自动测药（需游戏在主界面）。'

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Description $desc -Force | Out-Null

Write-Output "已注册计划任务：$TaskName"
Write-Output "  触发：每周 $Day $At（错过启动会尽快补跑）"
Write-Output "  执行：$Py `"$Script`""
Write-Output "  工作目录：$Repo"
Get-ScheduledTask -TaskName $TaskName | Select-Object TaskName, State | Format-Table -AutoSize
