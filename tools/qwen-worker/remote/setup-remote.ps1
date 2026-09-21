# 他の PC（Windows）で PowerShell から実行する。qwen-worker を SSH 越しに Claude Code / Codex へ登録する。
#
# 使い方:  powershell -ExecutionPolicy Bypass -File setup-remote.ps1 [-ServerIp <server-ip>] [-SkipServer]
#
# 前提: Windows 標準の OpenSSH クライアント（ssh.exe, ssh-keygen.exe）。
#       「設定 > アプリ > オプション機能 > OpenSSH クライアント」で入る。
#       -SkipServer を指定すると、サーバ側の登録（手順4）と疎通確認（手順5）を
#       スキップして、公開鍵と手で打つコマンドの表示だけで終わる。
param(
    [string]$ServerIp = "<server-ip>",
    [string]$ServerUser = "mt",
    [switch]$SkipServer
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
    Write-Host "[1/5] 鍵は既にあります: $keyFile"
} else {
    & ssh-keygen --% -q -t ed25519 -N "" -f "%QW_KEYFILE%" -C "%QW_COMMENT%"
    if ($LASTEXITCODE -ne 0) { throw "ssh-keygen が失敗しました（終了コード $LASTEXITCODE）" }
    Write-Host "[1/5] 鍵を作りました: $keyFile"
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
    Write-Host "[2/5] ssh config に Host qwen-worker は既にあります。触りません。"
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
    Write-Host "[2/5] ssh config に Host qwen-worker を追記しました。"
}

# 3. MCP 登録
if (Get-Command claude -ErrorAction SilentlyContinue) {
    & claude mcp get qwen-worker *> $null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[3/5] Claude Code: qwen-worker は既に登録済み。"
    } else {
        & claude mcp add -s user qwen-worker -- ssh -T qwen-worker
        Write-Host "[3/5] Claude Code: 登録しました。"
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
    Write-Host "[3/5] claude コマンドが無いので Claude Code の登録は省略。"
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

# 4. サーバーへ登録（公開鍵を stdin で渡す。ssh がパスワードを対話で 1 回聞く）
$pubFile = "$keyFile.pub"
if ($SkipServer) {
    Write-Host ""
    Write-Host "[4/5] -SkipServer 指定のためサーバへの登録と疎通確認をスキップします。"
    Write-Host "      手動登録: Get-Content $pubFile | ssh $ServerUser@$ServerIp 'bash ~/.local/share/qwen-worker/remote/add-remote-key.sh $pcName -'"
    Write-Host "      または \\$ServerIp\mt の共有経由でファイルを渡して add-remote-key.sh に食わせる。"
    Write-Host ""
    Get-Content "$pubFile"
    Write-Host ""
    Write-Host "受け入れ後の疎通確認:  ssh -n -T qwen-worker   （エラー無く即終了すれば OK）"
    Write-Host "MCP の確認:            claude mcp get qwen-worker  （Connected になること）"
} else {
    Write-Host ""
    Write-Host "[4/5] サーバー（$ServerIp）へ公開鍵を登録します: add-remote-key.sh $pcName"
    Write-Host "      ssh がパスワードを対話で 1 回聞きます。パスワードはこのスクリプトに渡しません。"
    # EAP=Stop の下で ssh が stderr を出しても例外にせず、終了コードで判定する
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    Get-Content $pubFile | ssh "$ServerUser@$ServerIp" "bash ~/.local/share/qwen-worker/remote/add-remote-key.sh ${pcName} -"
    $registerExit = $LASTEXITCODE
    $ErrorActionPreference = $prevEap
    if ($registerExit -ne 0) {
        Write-Host ""
        Write-Host "      !! サーバーへの登録に失敗しました（ssh 終了コード $registerExit）。"
        Write-Host "      手動で打ってください:"
        Write-Host "         Get-Content $pubFile | ssh $ServerUser@$ServerIp 'bash ~/.local/share/qwen-worker/remote/add-remote-key.sh $pcName -'"
        Write-Host "      公開鍵の内容は次の通りです:"
        Write-Host ""
        Get-Content "$pubFile"
        Write-Host ""
        exit 1
    }
    Write-Host "      登録コマンドを実行しました。"
}

# 5. 疎通確認
if (-not $SkipServer) {
    Write-Host ""
    Write-Host "[5/5] 疎通確認: ssh -n -T qwen-worker"
    # EAP=Stop の下でも ssh が stderr を出しても例外にはならないように Continue で回す
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & ssh -n -T qwen-worker
    $probeExit = $LASTEXITCODE
    $ErrorActionPreference = $prevEap
    $probeOk = ($probeExit -eq 0)
    if ($probeOk) {
        Write-Host ""
        Write-Host "      接続 OK"
    } else {
        Write-Host ""
        Write-Host "      接続 NG（終了コード $probeExit）"
        Write-Host "      原因の見方:"
        Write-Host "        - Enter passphrase for key と聞かれる / 鍵を拒否される: 鍵にパスフレーズが付いているか、authorized_keys に未登録。"
        Write-Host "          パスフレーズは ssh-keygen -p -f $keyFile （旧を入力、新は Enter 2 回）で外す。"
        Write-Host "        - Permission denied (publickey): authorized_keys にこの PC の鍵が無い。手順 4 を成功させるか、"
        Write-Host "          サーバー側で add-remote-key.sh $pcName を確認。"
        Write-Host "        - hostname 解決できない: ~/.ssh/config の HostName が $ServerIp か確認。"
    }
    if (Get-Command claude -ErrorAction SilentlyContinue) {
        Write-Host ""
        Write-Host "      MCP の確認: claude mcp get qwen-worker"
        & claude mcp get qwen-worker
    }
    Write-Host ""
    if ($probeOk) {
        Write-Host "設定完了。Claude Code / Codex から qwen-worker を呼べるはずです。"
    } else {
        Write-Host "設定は進んでいますが接続 NG でした。上の原因の見方を確認してください。"
        exit 1
    }
}
