#Requires -Version 5.1
[CmdletBinding()]
param(
    [string]$LogPath    = 'C:\MAA\debug\asst.log',
    [string]$LdConsole  = 'C:\leidian\LDPlayer9\ldconsole.exe',
    [int]$Index         = 0,
    [int]$PollSeconds   = 2,
    [int]$CloseTimeoutSeconds = 30,
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$logFile   = Join-Path $scriptDir '运行日志.txt'

function Write-Status {
    param([string]$Message)
    $line = '[{0}] {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Message
    Write-Host $line
    try { Add-Content -LiteralPath $logFile -Value $line -Encoding UTF8 } catch {}
}

# 返回 $true 表示该实例正在运行，$false 表示已关闭，$null 表示查询失败
function Test-InstanceRunning {
    param([int]$InstanceIndex)
    try {
        $output = & $LdConsole list2 2>$null
    } catch {
        return $null
    }
    foreach ($row in $output) {
        $parts = $row -split ','
        if ($parts.Count -ge 5 -and $parts[0] -match '^\d+$' -and [int]$parts[0] -eq $InstanceIndex) {
            return ($parts[4] -eq '1')
        }
    }
    return $null
}

function Close-Emulator {
    Write-Status "检测到 MAA 全部任务完成，准备关闭雷电实例 $Index ..."
    if ($DryRun) {
        Write-Status '[DryRun] 仅演示，不实际关闭。'
        return
    }
    try {
        & $LdConsole quit --index $Index | Out-Null
    } catch {
        Write-Status "发送关闭指令失败：$($_.Exception.Message)"
        return
    }
    $deadline = (Get-Date).AddSeconds($CloseTimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 1
        $running = Test-InstanceRunning -InstanceIndex $Index
        if ($running -eq $false) {
            Write-Status "已确认：雷电实例 $Index 已关闭。"
            return
        }
        if ($null -eq $running) { break }
    }
    Write-Status "已发送关闭指令，但未能在 ${CloseTimeoutSeconds}s 内确认关闭，请自行查看。"
}

Write-Status '===== MAA 跑完自动关雷电（常驻监视）启动 ====='
Write-Status "监视日志：$LogPath"
Write-Status "关闭目标：$LdConsole quit --index $Index"
Write-Status ("运行模式：{0}" -f ($(if ($DryRun) { 'DryRun（只检测，不关闭）' } else { '正常（检测到就真关）' })))
Write-Status '停止方式：按 Ctrl+C，或直接关闭本窗口。'

if (-not (Test-Path -LiteralPath $LdConsole)) {
    Write-Status "警告：找不到 ldconsole.exe：$LdConsole（真正关闭时会失败）"
}

$pos = 0
if (Test-Path -LiteralPath $LogPath) {
    $pos = (Get-Item -LiteralPath $LogPath).Length
} else {
    Write-Status "日志暂不存在，等待 MAA 生成：$LogPath"
}
Write-Status "从当前末尾开始监视（忽略历史记录，起始字节：$pos）。等待 MAA 跑完所有任务 ..."

while ($true) {
    Start-Sleep -Seconds $PollSeconds
    if (-not (Test-Path -LiteralPath $LogPath)) { continue }

    $fs = $null
    try {
        $fs = [System.IO.File]::Open($LogPath, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
        $len = $fs.Length
        if ($len -lt $pos) { $pos = 0 }   # 日志被轮转/截断，从头读
        if ($len -le $pos) { continue }

        [void]$fs.Seek($pos, [System.IO.SeekOrigin]::Begin)
        $count = [int]($len - $pos)
        if ($count -le 0) { continue }

        $buffer = New-Object byte[] $count
        $read = $fs.Read($buffer, 0, $count)
        if ($read -le 0) { continue }

        # 只处理到最后一个换行为止，避免读到半行
        $lastNl = -1
        for ($i = $read - 1; $i -ge 0; $i--) {
            if ($buffer[$i] -eq 10) { $lastNl = $i; break }
        }
        if ($lastNl -lt 0) { continue }

        $text = [System.Text.Encoding]::UTF8.GetString($buffer, 0, $lastNl + 1)
        $pos += ($lastNl + 1)

        foreach ($line in ($text -split "`n")) {
            if ($line -match 'AllTasksCompleted') {
                Close-Emulator
            }
        }
    } catch {
        Write-Status "读取日志出错：$($_.Exception.Message)"
    } finally {
        if ($fs) { $fs.Dispose() }
    }
}
