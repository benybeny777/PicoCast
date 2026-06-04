# Native Video Factory — Nuitka exe ビルドスクリプト（Windows）
#
# 配布用 onefile exe を作る。実行にはビルド用PCに Python + Nuitka + Cコンパイラが必要。
# 配布先PCには Python は不要（exe に同梱）。VOICEVOX / ffmpeg は別途インストール。
#
# 使い方:
#   .\build_exe.ps1
#
# 前提:
#   - .venv が作成済みで依存インストール済み
#   - 初回は MinGW64 を自動ダウンロードする（ネット必要・数百MB）
#
# 注意: 本スクリプトは「準備」段階。実ビルドは長時間かつ数回の調整が必要なことがある。
#       既知の残課題は BUILD.md を参照。

# 注意: pip / Nuitka / git などネイティブコマンドは進捗・通知を stderr に出す。
# $ErrorActionPreference="Stop" だと、その stderr 1行で NativeCommandError 扱いになり
# ビルド途中で停止する。ここでは Continue にして各ステップを $LASTEXITCODE で判定する。
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw ".venv が見つかりません。先に仮想環境を作成してください。" }

# 1. Nuitka を確認/導入（既に入っていれば pip が「Requirement already satisfied」を返す）
#    zstandard を入れると onefile が圧縮され exe が小さくなる（未導入だと圧縮スキップの警告が出る）。
Write-Host "Nuitka を確認/導入します..."
& $py -m pip install nuitka zstandard
if ($LASTEXITCODE -ne 0) { throw "Nuitka のインストールに失敗しました。" }

# 2. ビルドバージョンを焼き込む（exe では git が使えないため）
#    日付は HEAD コミット日付から取る（固定値で化石化しないように）。
#    build_app_version() と同じ規則: {コミット日付}.{コミット数}-{hash}
Write-Host "ビルドバージョンを生成します..."
$verBase     = (& git show -s '--format=%cd' '--date=format:%Y.%m.%d' HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or -not $verBase) { throw "コミット日付の取得に失敗しました。" }
$commitCount = (& git rev-list --count HEAD).Trim()
$commitHash  = (& git rev-parse --short HEAD).Trim()
$buildVersion = "$verBase.$commitCount-$commitHash"
Set-Content -Path "core/_build_version.py" -Value "BUILD_VERSION = `"$buildVersion`"" -Encoding ascii
Write-Host "BUILD_VERSION = $buildVersion"
# Windows のバージョンリソース用に数値のみへ整形（例: 2026.06.04 -> 2026.6.4）
$numVer = (($verBase -split '\.') | ForEach-Object { [int]$_ }) -join '.'

# 3. Nuitka ビルド（onefile standalone）
#    --include-data-dir で同梱リソースを含める。VOICEVOX/ffmpeg は同梱しない。
Write-Host "Nuitka ビルドを開始します（長時間かかります）..."
& $py -m nuitka `
    --standalone --onefile `
    --assume-yes-for-downloads `
    --include-windows-runtime-dlls=yes `
    --onefile-tempdir-spec="{CACHE_DIR}\NativeVideoFactory\{VERSION}" `
    --nofollow-import-to=PIL.ImageQt `
    --nofollow-import-to=PIL.ImageTk `
    --output-dir=dist `
    --output-filename=NativeVideoFactory.exe `
    --company-name="Native Video Factory" `
    --product-name="Native Video Factory" `
    --product-version=$numVer `
    --file-version=$numVer `
    --include-data-dir=web_app/templates=web_app/templates `
    --include-data-dir=web_app/static=web_app/static `
    --include-data-dir=legal=legal `
    --include-data-dir=config/SEED=config/SEED `
    --include-data-dir=config/prompt_profiles=config/prompt_profiles `
    --include-data-dir=config/samples=config/samples `
    --include-data-dir=assets=assets `
    --include-package=web_app `
    --include-package=core `
    --include-package=workers `
    --include-package=config `
    --include-package=uvicorn `
    --include-package=fastapi `
    --include-package=starlette `
    --include-package=jinja2 `
    web_app/app.py

if ($LASTEXITCODE -ne 0) { throw "Nuitka ビルドに失敗しました。BUILD.md の残課題を参照してください。" }
Write-Host "完了: dist\NativeVideoFactory.exe"

# 4. コード署名（自己署名の証明書が CurrentUser\My にあれば exe に署名する）
#    注意: onefile の外側 exe のみ署名される。展開される app.dll は署名されないため
#          Defender のML誤検知対策にはならない（発行元識別のための署名）。
$exePath = Join-Path $root "dist\NativeVideoFactory.exe"
$signCert = Get-ChildItem Cert:\CurrentUser\My |
    Where-Object { $_.Subject -eq "CN=Native Video Factory Self-Signed" -and $_.HasPrivateKey } |
    Select-Object -First 1
if ($signCert) {
    Write-Host "コード署名します（自己署名）..."
    $sig = Set-AuthenticodeSignature -FilePath $exePath -Certificate $signCert `
        -HashAlgorithm SHA256 -TimestampServer "http://timestamp.digicert.com"
    if ($sig.Status -ne 'Valid') {
        # タイムスタンプ不通などのときはタイムスタンプ無しで署名し直す
        $sig = Set-AuthenticodeSignature -FilePath $exePath -Certificate $signCert -HashAlgorithm SHA256
    }
    Write-Host ("署名ステータス: " + $sig.Status)
} else {
    Write-Host "（署名スキップ: 証明書が未作成。署名するには先に .\make_codesign_cert.ps1 を実行してください）"
}
