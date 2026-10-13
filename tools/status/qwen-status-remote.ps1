# 他の PC（Windows PowerShell）から、A30 サーバー上の qwen-status.sh を ssh で呼ぶ。
#
# 使い方:  powershell -ExecutionPolicy Bypass -File qwen-status-remote.ps1 -Server <user>@<server-ip> [-Watch 秒] [-Lines N]
#   接続先は -Server か環境変数 LOCALAI_SERVER_HOST（<user>@<server-ip> の形）で必ず指定する。
#   例: -Server alice@192.168.1.10
#   サーバーのログインパスワードを ssh が聞く（qwen-worker 用の鍵は強制コマンド付きで使えない）。
#   前提: Windows 標準の OpenSSH クライアント（ssh.exe）。
param(
    [string]$Server = $env:LOCALAI_SERVER_HOST,
    [int]$Watch = 0,
    [int]$Lines = 3
)
$ErrorActionPreference = "Stop"
if ([string]::IsNullOrWhiteSpace($Server)) {
    Write-Error "接続先が未指定です。-Server か環境変数 LOCALAI_SERVER_HOST で指定してください。例: -Server alice@192.168.1.10" -ErrorAction Continue
    exit 2
}
$remoteArgs = "--lines $Lines"
if ($Watch -gt 0) { $remoteArgs = "$remoteArgs --watch $Watch" }
# -t は --watch の画面更新と Ctrl-C のため。リダイレクトは使わない（PowerShell では < が使えない）
& ssh -t $Server "bash ~/Proj/localai/tools/status/qwen-status.sh $remoteArgs"
exit $LASTEXITCODE
