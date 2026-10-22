# 注册 / 注销「方舟·凌晨基建换班」Windows 计划任务
#
#   每天 02:00 跑 scripts/night-infrast/night_infrast.py：
#     · 单客户端检查（MAA GUI 在跑 → 跳过）
#     · 确保雷电 + 游戏在线（不在线就拉起，冷启动点游戏图标）
#     · 跑一次 MAA `Infrast`（Custom 自定义换班 `mode=10000`，B班 `plan_index=0`；口径见 maa_week.INFRAST_*）
#     · 跑完关雷电（ldconsole quit）
#
# ⚠ **故意不设 -StartWhenAvailable**：2:00 电脑不在线（关机/睡眠）就**整晚不跑、不补跑**
#   —— 这正是用户要的「2:00 在线才跑，不在就算了」。所以**不要**给它加 -StartWhenAvailable。
#   （对比：14:00 的「方舟·每日日常」是设了补跑的，两者语义不同。）
#
# 用法（普通 PowerShell 即可，无需管理员）：
#   powershell -ExecutionPolicy Bypass -File scripts\night-infrast\install_task.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\night-infrast\install_task.ps1 -Uninstall
#   powershell -ExecutionPolicy Bypass -File scripts\night-infrast\install_task.ps1 -At 02:00
param(
    [switch]$Uninstall,
    [string]$At = '02:00'
)

$ErrorActionPreference = 'Stop'
$TaskName = '方舟·凌晨基建换班'

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
$Script = Join-Path $Repo 'scripts\night-infrast\night_infrast.py'
$Py     = 'C:\Python314\pythonw.exe'

if (-not (Test-Path $Script)) { throw "找不到脚本：$Script" }
if (-not (Test-Path $Py))     { throw "找不到 pythonw：$Py（按 AGENTS.md，Python 在 C:\Python314）" }

$action  = New-ScheduledTaskAction -Execute $Py -Argument ('"' + $Script + '"') -WorkingDirectory $Repo
$trigger = New-ScheduledTaskTrigger -Daily -At $At
# 注意：这里**不加** -StartWhenAvailable（→ 错过就不跑）。
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -DontStopOnIdleEnd `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 45) `
    -MultipleInstances IgnoreNew

$desc = '每天 02:00：若电脑在线则跑一次 MAA 基建换班（Infrast Custom mode=10000，B班 plan_index=0）→ 跑完关雷电；2:00 不在线则不跑、不补跑。'

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Description $desc -Force | Out-Null

Write-Output "已注册计划任务：$TaskName"
Write-Output "  触发：每天 $At（**不补跑**：2:00 不在线就整晚不跑）"
Write-Output "  执行：$Py `"$Script`""
Write-Output "  工作目录：$Repo"
Write-Output "  日志：$Repo\scripts\night-infrast\运行日志.txt"
Get-ScheduledTask -TaskName $TaskName | Select-Object TaskName, State | Format-Table -AutoSize
