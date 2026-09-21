# Windows 11 の他の PC で PowerShell 5.1 / 7 のどちらからも実行する。
# local-ai-bridge を WSL2 の中に入れ、Windows 側の Claude Code / Codex から使えるようにする。
#
# 使い方: powershell -ExecutionPolicy Bypass -File setup-workpc.ps1
#             [-ServerIp <server-ip>] [-ServerUser mt]
#             [-Distro <WSLディストリ名>] [-InstallDir ~/local-ai-bridge]
#             [-SkipServer] [-NoRules]
#
# 注意: bridge 本体は fcntl を使うため Windows ネイティブでは動かない。
#       本体導入は同じディレクトリの bash 版 setup-workpc.sh を WSL2 内で実行することに任せる。
#       パスワードを扱わない。sudo / 管理者権限を使わない。
param(
    [string]$ServerIp   = "<server-ip>",
    [string]$ServerUser = "mt",
    [string]$Distro     = "",
    [string]$InstallDir = "~/local-ai-bridge",
    [switch]$SkipServer,
    [switch]$NoRules
)
$ErrorActionPreference = "Stop"

function Escape-DoubleQuotedBashValue {
    param([string]$sourceValue)
    return ($sourceValue -replace '([`"\\$])', '\$1')
}

function Convert-PsObjectToWritable {
    param($sourceValue)
    if ($null -eq $sourceValue) { return $null }
    if ($sourceValue -is [System.Collections.IDictionary]) { return $sourceValue }
    if (($sourceValue -is [System.Collections.IEnumerable]) -and ($sourceValue -isnot [string])) {
        $convertedItems = New-Object System.Collections.Generic.List[object]
        foreach ($sourceItem in $sourceValue) {
            [void]$convertedItems.Add((Convert-PsObjectToWritable $sourceItem))
        }
        return $convertedItems.ToArray()
    }
    $convertedTable = @{}
    foreach ($sourceProperty in $sourceValue.PSObject.Properties) {
        $convertedTable[$sourceProperty.Name] = Convert-PsObjectToWritable $sourceProperty.Value
    }
    return $convertedTable
}

# ---------------------------------------------------------------- [1/4]
Write-Host "== local-ai-bridge WSL2 導入（Windows 側） =="
Write-Host "サーバー: $ServerUser@$ServerIp / 導入先（WSL 内）: $InstallDir / ディストリ: $($Distro -replace '^$', '既定')"
Write-Host ""
Write-Host "[1/4] WSL2 の確認"
if (-not (Get-Command wsl -ErrorAction SilentlyContinue)) {
    Write-Host "      wsl.exe が見つかりません。次に進めてください:"
    Write-Host "        1. wsl --install   （WSL2 と既定ディストリを入れます）"
    Write-Host "        2. 案内があれば PC を再起動し、`wsl -l -q` にディストリが出ることを確認"
    Write-Host "        3. このスクリプトを再実行（既定ディストリと異なるなら -Distro で指定）"
    exit 2
}
$previousErrorAction = $ErrorActionPreference
$ErrorActionPreference = "Continue"
$registeredDistros = @(& wsl -l -q | ForEach-Object { $_.ToString().Trim() } | Where-Object { $_.Length -gt 0 })
$ErrorActionPreference = $previousErrorAction
if ($registeredDistros.Count -eq 0) {
    Write-Host "      `wsl -l -q` にディストリがありません。次に進めてください:"
    Write-Host "        1. wsl --install   （WSL2 と既定ディストリを入れます）"
    Write-Host "        2. 案内があれば PC を再起動し、`wsl -l -q` にディストリが出ることを確認"
    Write-Host "        3. このスクリプトを再実行（既定ディストリと異なるなら -Distro で指定）"
    exit 2
}
if ($Distro) {
    Write-Host "      使う WSL2 ディストリ: $Distro"
} else {
    Write-Host "      使う WSL2 ディストリ（既定ディストリ）: $($registeredDistros[0])"
}
$defaultDistroForDisplay = if ($Distro) { $Distro } else { $registeredDistros[0] }
Write-Host "[1/4] WSL2 ディストリ: 既にあります"

$wslScopeArgs = @()
if ($defaultDistroForDisplay) { $wslScopeArgs = @("-d", $defaultDistroForDisplay) }

# ---------------------------------------------------------------- [2/4]
Write-Host ""
Write-Host "[2/4] bash 版 setup-workpc.sh を WSL2 内で実行"
$setupShellPath = Join-Path $PSScriptRoot "setup-workpc.sh"
if (-not (Test-Path $setupShellPath)) {
    Write-Host "      bash 版が見つかりません: $setupShellPath"
    exit 1
}
$wslSetupShellPath = (@(& wsl @wslScopeArgs "wslpath" "-a" $setupShellPath) | ForEach-Object { $_.ToString().Trim() })
if (-not $wslSetupShellPath) {
    Write-Host "      WSL パス変換（wslpath -a）に失敗しました: $setupShellPath"
    exit 1
}
$shellArgList = @("--server-ip", $ServerIp, "--server-user", $ServerUser, "--install-dir", $InstallDir)
if ($SkipServer) { $shellArgList += "--skip-server" }
if ($NoRules) { $shellArgList += "--no-rules" }
$quotedShellArgs = @($shellArgList | ForEach-Object { '"' + (Escape-DoubleQuotedBashValue $_) + '"' })
$innerBashCommand = '"' + (Escape-DoubleQuotedBashValue $wslSetupShellPath) + '" ' + ($quotedShellArgs -join ' ')
Write-Host "      $innerBashCommand"

$wslExecutionArgs = @()
if ($defaultDistroForDisplay) { $wslExecutionArgs = @("-d", $defaultDistroForDisplay) }
$wslExecutionArgs += @("--", "bash", "-lc", $innerBashCommand)
$previousErrorAction = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& wsl @wslExecutionArgs
$shellExitCode = $LASTEXITCODE
$ErrorActionPreference = $previousErrorAction
if ($shellExitCode -ne 0) {
    Write-Host ""
    Write-Host "      !! bash 版実行に失敗しました（終了コード $shellExitCode）"
    Write-Host "[2/4] bridge 本体導入: 作成しました"
    exit $shellExitCode
}
Write-Host "[2/4] bridge 本体導入: 作成しました（既にあったものの上書きは「既にあります」で上に表示）"

# ---------------------------------------------------------------- [3/4]
Write-Host ""
Write-Host "[3/4] Windows 側の MCP 登録"
$wslHomeDirectory = (@(& wsl @wslScopeArgs "bash" "-lc" 'echo $HOME') | ForEach-Object { $_.ToString().Trim() })
if (-not $wslHomeDirectory) {
    Write-Host "      WSL 内の `echo \$HOME` が空を返しました"
    exit 1
}
$wslBridgeDirectory = ($InstallDir -replace '\\', '/')
if ($wslBridgeDirectory -eq "~") {
    $wslBridgeDirectory = $wslHomeDirectory
} elseif ($wslBridgeDirectory.StartsWith("~/")) {
    $wslBridgeDirectory = $wslHomeDirectory + "/" + $wslBridgeDirectory.Substring(2)
}
$bridgeLaunchTarget = $wslBridgeDirectory + "/run-local-ai-task"
$mcpWslArgs = @()
if ($defaultDistroForDisplay) { $mcpWslArgs = @("-d", $defaultDistroForDisplay) }
$mcpWslArgs += @("-e", $bridgeLaunchTarget, "mcp")

$stage3AddedSomething = $false
$claudeAvailable = [bool](Get-Command claude -ErrorAction SilentlyContinue)
$codexAvailable  = [bool](Get-Command codex  -ErrorAction SilentlyContinue)

if ($claudeAvailable) {
    $previousErrorAction = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & claude mcp get local-ai-bridge *> $null
    $claudeAlreadyRegistered = ($LASTEXITCODE -eq 0)
    $ErrorActionPreference = $previousErrorAction
    if ($claudeAlreadyRegistered) {
        Write-Host "      Claude Code: local-ai-bridge は既に登録済み（スキップ）。"
    } else {
        & claude mcp add -s user local-ai-bridge -- wsl @mcpWslArgs
        if ($LASTEXITCODE -ne 0) {
            Write-Host "      !! claude mcp add が失敗しました（終了コード $LASTEXITCODE）。手動で次を実行してください:"
            Write-Host "         claude mcp add -s user local-ai-bridge -- wsl $($mcpWslArgs -join ' ')"
            exit 1
        }
        Write-Host "      Claude Code: 登録しました。"
        $stage3AddedSomething = $true
    }
    # settings.json の env タイムアウト（tools/qwen-worker/remote/setup-remote.ps1 の [3/5] と同じ流儀）
    $settingsFile = Join-Path $HOME ".claude\settings.json"
    $settingsTable = @{}
    if (Test-Path $settingsFile) {
        $settingsText = Get-Content $settingsFile -Raw
        if ($PSVersionTable.PSVersion.Major -ge 6) {
            $settingsTable = $settingsText | ConvertFrom-Json -AsHashtable
        } else {
            $settingsTable = Convert-PsObjectToWritable ($settingsText | ConvertFrom-Json)
        }
    }
    if ($settingsTable -isnot [System.Collections.IDictionary]) { $settingsTable = @{} }
    if (-not $settingsTable.ContainsKey("env")) { $settingsTable["env"] = @{} }
    if ($settingsTable["env"] -isnot [System.Collections.IDictionary]) { $settingsTable["env"] = @{} }
    $settingsChanged = $false
    foreach ($envPair in @(@("MCP_TOOL_TIMEOUT","2100000"), @("MCP_TIMEOUT","30000"))) {
        if ("$($settingsTable['env'][$envPair[0]])" -ne $envPair[1]) {
            $settingsTable["env"][$envPair[0]] = $envPair[1]
            $settingsChanged = $true
        }
    }
    if ($settingsChanged) {
        if (Test-Path $settingsFile) {
            $backupFile = "$settingsFile.bak.$(Get-Date -Format 'yyyyMMdd-HHmmss')"
            Copy-Item -Path $settingsFile -Destination $backupFile -Force
            Write-Host "      退避しました: $backupFile"
        }
        New-Item -ItemType Directory -Force -Path (Split-Path $settingsFile -Parent) | Out-Null
        ($settingsTable | ConvertTo-Json -Depth 10) | Set-Content -Path $settingsFile -Encoding utf8
        Write-Host "      settings.json の env に MCP タイムアウトを追加しました（他の設定は無傷）。"
        $stage3AddedSomething = $true
    } else {
        Write-Host "      settings.json の MCP タイムアウトは既に設定済み。"
    }
} else {
    Write-Host "      claude コマンドが無いので Claude Code への登録は省略。"
}

if ($codexAvailable) {
    $previousErrorAction = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & codex mcp get local-ai-bridge *> $null
    $codexAlreadyRegistered = ($LASTEXITCODE -eq 0)
    $ErrorActionPreference = $previousErrorAction
    if ($codexAlreadyRegistered) {
        Write-Host "      Codex: local-ai-bridge は既に登録済み（スキップ）。"
    } else {
        & codex mcp add local-ai-bridge -- wsl @mcpWslArgs
        if ($LASTEXITCODE -ne 0) {
            Write-Host "      !! codex mcp add が失敗しました（終了コード $LASTEXITCODE）。手動で次を実行してください:"
            Write-Host "         codex mcp add local-ai-bridge -- wsl $($mcpWslArgs -join ' ')"
            exit 1
        }
        Write-Host "      Codex: 登録しました。"
        $stage3AddedSomething = $true
    }
} else {
    Write-Host "      codex コマンドが無いので Codex への登録は省略。"
}
$stage3Outcome = if ($stage3AddedSomething) { "作成しました" } else { "既にあります" }
Write-Host "[3/4] Windows 側の MCP 登録: $stage3Outcome"

# ---------------------------------------------------------------- [4/4]
Write-Host ""
Write-Host "[4/4] 確認"
if ($claudeAvailable) {
    $previousErrorAction = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & claude mcp get local-ai-bridge
    $showGetExit = $LASTEXITCODE
    $ErrorActionPreference = $previousErrorAction
    if ($showGetExit -eq 0) {
        Write-Host "[4/4] MCP 登録状態: 既にあります"
    } else {
        Write-Host "[4/4] MCP 登録状態: 作成しました（`claude mcp get` は終了コード $showGetExit）"
    }
} else {
    Write-Host "      claude コマンドが無いので `claude mcp get` の表示は省略します。"
    Write-Host "[4/4] MCP 登録状態: 作成しました"
}
Write-Host ""
Write-Host "使うたび: WSL 内で a30-tunnel start を実行してから Claude Code / Codex を使う"
Write-Host "この Windows→WSL2 の経路は未検証。動かなければ WSL 内の Claude Code から使う"
