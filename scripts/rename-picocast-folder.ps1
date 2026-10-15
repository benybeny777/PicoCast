#Requires -Version 5.1
[CmdletBinding(SupportsShouldProcess = $true)]
param([switch]$CheckOnly)

$ErrorActionPreference = 'Stop'
$expectedParent = 'C:\00_PG'
$sourceName = '00_yukkurijidou'
$destinationName = '22_PicoCast'
$source = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$parent = [IO.Path]::GetDirectoryName($source)
$destination = [IO.Path]::GetFullPath((Join-Path $parent $destinationName))

# 別の場所にコピーしたスクリプトで、意図しないフォルダを移動させない。
if ($parent -ine $expectedParent -or [IO.Path]::GetFileName($source) -ine $sourceName) {
    throw 'このスクリプトは C:\00_PG\00_yukkurijidou\scripts から実行してください。'
}
if ([IO.Path]::GetDirectoryName($destination) -ine $expectedParent) {
    throw '改名先が想定した親フォルダの外を指しています。処理を中止しました。'
}
$item = Get-Item -LiteralPath $source
if (-not $item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
    throw '改名元が通常のフォルダではありません。処理を中止しました。'
}
if (Test-Path -LiteralPath $destination) {
    throw "改名先が既に存在します。上書きしません: $destination"
}
Get-Command git -ErrorAction Stop | Out-Null
$gitRoot = & git -C $source rev-parse --show-toplevel
if ($LASTEXITCODE -ne 0 -or [IO.Path]::GetFullPath($gitRoot) -ine $source) {
    throw '改名元の Git ルートを確認できません。処理を中止しました。'
}

# 引数へ対象パスが無い起動形もあるため、Web UI / runner の候補があれば停止する。
# プロセスを勝手に終了せず、認証情報を含み得る引数も表示しない。
$running = @(Get-CimInstance Win32_Process | Where-Object {
    $_.ProcessId -ne $PID -and $_.Name -match '^(pythonw?|uvicorn|NativeVideoFactory|PicoCast)\.exe$' -and (
        $_.ExecutablePath -like "$source\*" -or
        $_.CommandLine -match '(?i)(web_app\.app|workers\.runner|--post-fixed-comments)'
    )
})
if ($running.Count -gt 0) {
    $processIds = ($running | ForEach-Object { $_.ProcessId }) -join ', '
    throw "Web UI / runner などの停止を確認してください。対象候補 PID: $processIds"
}
Write-Host "改名元: $source"
Write-Host "改名先: $destination"
if ($CheckOnly) {
    Write-Host '事前確認が通りました。改名はしていません。実行前に Codex・Claude・エディターを閉じてください。'
    return
}
if ($PSCmdlet.ShouldProcess($source, "$destinationName へ改名")) {
    # 実行中のシェル自身が改名元を作業ディレクトリとして保持しないようにする。
    Set-Location -LiteralPath $parent
    Rename-Item -LiteralPath $source -NewName $destinationName
    & git -C $destination worktree repair
    if ($LASTEXITCODE -ne 0) {
        throw "フォルダは改名済みですが、Git worktree の参照修復に失敗しました。新フォルダで復旧してください: $destination"
    }
    Write-Host '改名と Git worktree の参照修復が完了しました。'
    Write-Host "Codex で $destination を開き直してください。"
    Write-Host 'legacy への移動と Python 環境の切り替えは、このコマンドでは行いません。'
}
