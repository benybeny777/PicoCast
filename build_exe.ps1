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
#    python -c に複雑な文字列を渡すと PowerShell の引用符解釈で壊れるため、
#    バージョン生成は PowerShell 側で行い、ファイル書き出しもここで行う。
Write-Host "ビルドバージョンを生成します..."
$verBase = (& $py -c "from core.gui_support import APP_VERSION_BASE; print(APP_VERSION_BASE)").Trim()
if ($LASTEXITCODE -ne 0 -or -not $verBase) { throw "APP_VERSION_BASE の取得に失敗しました。" }
$commitCount = (& git rev-list --count HEAD).Trim()
$commitHash  = (& git rev-parse --short HEAD).Trim()
$buildVersion = "$verBase.$commitCount-$commitHash"
Set-Content -Path "core/_build_version.py" -Value "BUILD_VERSION = `"$buildVersion`"" -Encoding ascii
Write-Host "BUILD_VERSION = $buildVersion"
# Windows のバージョンリソース用に数値のみへ整形（例: 2026.05.19 -> 2026.5.19）
$numVer = (($verBase -split '\.') | ForEach-Object { [int]$_ }) -join '.'

# 3. Nuitka ビルド（onefile standalone）
#    --include-data-dir で同梱リソースを含める。VOICEVOX/ffmpeg は同梱しない。
Write-Host "Nuitka ビルドを開始します（長時間かかります）..."
& $py -m nuitka `
    --standalone --onefile `
    --assume-yes-for-downloads `
    --include-windows-runtime-dlls=yes `
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
