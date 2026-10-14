# 注册 / 注销「方舟·每日日常」Windows 计划任务
#
#   每天 14:00 跑 scripts/daily-auto/daily_auto.py：
#     · 森空岛签到（skland_cli.py checkin）—— 失败只记日志、不中断
#     · 直驱 MaaCore 跑当天日常（maa_week.py run，内置冷启动自动拉起雷电）
#     · 跑完关雷电（ldconsole quit）
#   「错过的启动」= 开机后尽快补跑（-StartWhenAvailable）：14:00 没开机，开机后自动补。
#
# 用法（普通 PowerShell 即可，无需管理员）：
#   powershell -ExecutionPolicy Bypass -File scripts\daily-auto\install_task.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\daily-auto\install_task.ps1 -Uninstall
#   powershell -ExecutionPolicy Bypass -File scripts\daily-auto\install_task.ps1 -At 14:00
param(
    [switch]$Uninstall,
    [string]$At = '14:00'
)

$ErrorActionPreference = 'Stop'
$TaskName = '方舟·每日日常'

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
$Script = Join-Path $Repo 'scripts\daily-auto\daily_auto.py'
$Py     = 'C:\Python314\pythonw.exe'

if (-not (Test-Path $Script)) { throw "找不到脚本：$Script" }
if (-not (Test-Path $Py))     { throw "找不到 pythonw：$Py（按 AGENTS.md，Python 在 C:\Python314）" }

$action  = New-ScheduledTaskAction -Execute $Py -Argument ('"' + $Script + '"') -WorkingDirectory $Repo
$trigger = New-ScheduledTaskTrigger -Daily -At $At
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 150) `
    -MultipleInstances IgnoreNew

$desc = '每日 14:00 自动日常：森空岛签到 → 直驱 MaaCore 跑当天日常（自动拉起雷电）→ 跑完关雷电。签到失败只记日志、不中断。'

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Description $desc -Force | Out-Null

Write-Output "已注册计划任务：$TaskName"
Write-Output "  触发：每天 $At（错过启动会尽快补跑）"
Write-Output "  执行：$Py `"$Script`""
Write-Output "  工作目录：$Repo"
Write-Output "  日志：$Repo\scripts\daily-auto\运行日志.txt"
Get-ScheduledTask -TaskName $TaskName | Select-Object TaskName, State | Format-Table -AutoSize
