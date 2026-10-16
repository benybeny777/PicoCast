Set-Location $PSScriptRoot
$ErrorActionPreference = 'Stop'
Get-Command uv -CommandType Application -ErrorAction Stop | Out-Null
$interpreter = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $interpreter -PathType Leaf)) {
    throw 'Python環境がありません。uv sync --locked --group build --group dev を実行してください。'
}
$version = & $interpreter -I -S -c 'import sys; print(*sys.version_info[:2],sep=chr(46))'
if ($LASTEXITCODE -ne 0 -or [string]$version -ne '3.12') {
    throw 'Python 3.12環境が必要です。既存環境は scripts/switch-python312.ps1 -CheckOnly から切り替えてください。'
}
# 起動時に依存を入れ替えず、uv.lockで準備した環境を使う。
& uv run --locked --no-sync python -m web_app.app --open-browser
if ($LASTEXITCODE -ne 0) { throw 'PicoCastの起動に失敗しました。デバッグログを確認してください。' }
