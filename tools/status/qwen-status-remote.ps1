# 他の PC（Windows PowerShell）から、A30 サーバー上の qwen-status.sh を ssh で呼ぶ。
#
# 使い方:  powershell -ExecutionPolicy Bypass -File qwen-status-remote.ps1 [-Server mt@<server-ip>] [-Watch 秒] [-Lines N]
#   サーバーのログインパスワードを ssh が聞く（qwen-worker 用の鍵は強制コマンド付きで使えない）。
#   前提: Windows 標準の OpenSSH クライアント（ssh.exe）。
param(
    [string]$Server = "mt@<server-ip>",
    [int]$Watch = 0,
    [int]$Lines = 3
)
$ErrorActionPreference = "Stop"
$remoteArgs = "--lines $Lines"
if ($Watch -gt 0) { $remoteArgs = "$remoteArgs --watch $Watch" }
# -t は --watch の画面更新と Ctrl-C のため。リダイレクトは使わない（PowerShell では < が使えない）
& ssh -t $Server "bash ~/Proj/localai/tools/status/qwen-status.sh $remoteArgs"
exit $LASTEXITCODE
