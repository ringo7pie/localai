# 他の PC（Windows）で PowerShell から実行する。qwen-worker を SSH 越しに Claude Code / Codex へ登録する。
#
# 使い方:  powershell -ExecutionPolicy Bypass -File setup-remote.ps1 [-ServerIp <server-ip>]
#
# 前提: Windows 標準の OpenSSH クライアント（ssh.exe, ssh-keygen.exe）。
#       「設定 > アプリ > オプション機能 > OpenSSH クライアント」で入る。
param(
    [string]$ServerIp = "<server-ip>",
    [string]$ServerUser = "mt"
)
$ErrorActionPreference = "Stop"

$sshDir  = Join-Path $HOME ".ssh"
$keyFile = Join-Path $sshDir "qwen-worker"
$pcName  = $env:COMPUTERNAME

New-Item -ItemType Directory -Force -Path $sshDir | Out-Null

# 1. 鍵（パスフレーズ無し。MCP の ssh 呼び出しは対話できないので、パスフレーズ付きだと使えない）
# 注意: PowerShell 7.3 以降は `-N '""'` が文字列 "" そのものをパスフレーズにしてしまう。
#       `--%`（停止解析）で ssh-keygen にそのまま渡し、%VAR% は環境変数として展開させる。
$env:QW_KEYFILE = $keyFile
$env:QW_COMMENT = "qwen-worker@$pcName"
if (Test-Path $keyFile) {
    Write-Host "[1/4] 鍵は既にあります: $keyFile"
} else {
    & ssh-keygen --% -q -t ed25519 -N "" -f "%QW_KEYFILE%" -C "%QW_COMMENT%"
    if ($LASTEXITCODE -ne 0) { throw "ssh-keygen が失敗しました（終了コード $LASTEXITCODE）" }
    Write-Host "[1/4] 鍵を作りました: $keyFile"
}
# パスフレーズ無しで読めるか確認する（読めなければ MCP から使えない）
# （--% の後ろにリダイレクトを書くと引数として渡ってしまうので、代入で出力を捨てる）
$null = & ssh-keygen --% -y -P "" -f "%QW_KEYFILE%"
if ($LASTEXITCODE -ne 0) {
    Write-Host "      !! この鍵はパスフレーズ付きです。MCP からは使えません。次のどちらかで直してください:"
    Write-Host "         a) パスフレーズを外す:  ssh-keygen -p -f $keyFile   （旧パスフレーズを入れ、新は Enter を 2 回）"
    Write-Host "         b) 作り直す: $keyFile と $keyFile.pub を削除して、このスクリプトを再実行。"
    Write-Host "            その場合サーバ側で remove-remote-key.sh <PC名> で古い鍵を消してから、新しい公開鍵を受け入れ直す。"
}

# 2. ssh config
$configFile = Join-Path $sshDir "config"
if (-not (Test-Path $configFile)) { New-Item -ItemType File -Path $configFile | Out-Null }
$configText = Get-Content $configFile -Raw -ErrorAction SilentlyContinue
if ($configText -match "(?m)^Host qwen-worker\s*$") {
    Write-Host "[2/4] ssh config に Host qwen-worker は既にあります。触りません。"
} else {
    $block = @"

Host qwen-worker
  HostName $ServerIp
  User $ServerUser
  IdentityFile $keyFile
  IdentitiesOnly yes
  ServerAliveInterval 30
  RequestTTY no
"@
    Add-Content -Path $configFile -Value $block -Encoding ascii
    Write-Host "[2/4] ssh config に Host qwen-worker を追記しました。"
}

# 3. MCP 登録
if (Get-Command claude -ErrorAction SilentlyContinue) {
    & claude mcp get qwen-worker *> $null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[3/4] Claude Code: qwen-worker は既に登録済み。"
    } else {
        & claude mcp add -s user qwen-worker -- ssh -T qwen-worker
        Write-Host "[3/4] Claude Code: 登録しました。"
    }
    $settings = Join-Path $HOME ".claude\settings.json"
    $data = @{}
    if (Test-Path $settings) { $data = Get-Content $settings -Raw | ConvertFrom-Json -AsHashtable }
    if (-not $data.ContainsKey("env")) { $data["env"] = @{} }
    $changed = $false
    foreach ($pair in @(@("MCP_TOOL_TIMEOUT","2100000"), @("MCP_TIMEOUT","30000"))) {
        if ($data["env"][$pair[0]] -ne $pair[1]) { $data["env"][$pair[0]] = $pair[1]; $changed = $true }
    }
    if ($changed) {
        New-Item -ItemType Directory -Force -Path (Split-Path $settings) | Out-Null
        $data | ConvertTo-Json -Depth 20 | Set-Content -Path $settings -Encoding utf8
        Write-Host "      settings.json の env にタイムアウトを足しました（他の設定は無傷）。"
    } else {
        Write-Host "      settings.json のタイムアウトは既に設定済み。"
    }
} else {
    Write-Host "[3/4] claude コマンドが無いので Claude Code の登録は省略。"
}

if (Get-Command codex -ErrorAction SilentlyContinue) {
    & codex mcp get qwen-worker *> $null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "      Codex: qwen-worker は既に登録済み。"
    } else {
        & codex mcp add qwen-worker -- ssh -T qwen-worker
        Write-Host "      Codex: 登録しました。"
    }
    $codexHome = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $HOME ".codex" }
    $codexCfg  = Join-Path $codexHome "config.toml"
    if (Test-Path $codexCfg) {
        $toml = Get-Content $codexCfg -Raw
        if ($toml -match "\[mcp_servers\.qwen-worker\]" -and $toml -notmatch "tool_timeout_sec") {
            $toml = $toml -replace "(\[mcp_servers\.qwen-worker\]\r?\n(?:[^\[].*\r?\n)*)", "`$1tool_timeout_sec = 2100`nstartup_timeout_sec = 30`n"
            Set-Content -Path $codexCfg -Value $toml -Encoding utf8
            Write-Host "      config.toml にタイムアウトを足しました。"
        }
    }
} else {
    Write-Host "      codex コマンドが無いので Codex の登録は省略。"
}

# 4. 公開鍵を表示
Write-Host ""
Write-Host "[4/4] この公開鍵をサーバ（$ServerIp）側で受け入れてください:"
Write-Host "      Get-Content $keyFile.pub | ssh $ServerUser@$ServerIp 'bash ~/.local/share/qwen-worker/remote/add-remote-key.sh $pcName -'"
Write-Host "      または \\$ServerIp\mt の共有経由でファイルを渡して add-remote-key.sh に食わせる。"
Write-Host ""
Get-Content "$keyFile.pub"
Write-Host ""
Write-Host "受け入れ後の疎通確認:  ssh -n -T qwen-worker   （エラー無く即終了すれば OK）"
Write-Host "MCP の確認:            claude mcp get qwen-worker  （Connected になること）"
