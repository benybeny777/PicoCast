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

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw ".venv が見つかりません。先に仮想環境を作成してください。" }

# 1. Nuitka を確認（無ければ導入）
& $py -m pip show nuitka *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Nuitka をインストールします..."
    & $py -m pip install nuitka
}

# 2. ビルドバージョンを焼き込む（exe では git が使えないため）
Write-Host "ビルドバージョンを生成します..."
& $py -c "from core.gui_support import APP_VERSION_BASE; import subprocess; c=subprocess.check_output(['git','rev-list','--count','HEAD'],text=True).strip(); h=subprocess.check_output(['git','rev-parse','--short','HEAD'],text=True).strip(); open('core/_build_version.py','w',encoding='utf-8').write(f'BUILD_VERSION = \"{APP_VERSION_BASE}.{c}-{h}\"\n')"

# 3. Nuitka ビルド（onefile standalone）
#    --include-data-dir で同梱リソースを含める。VOICEVOX/ffmpeg は同梱しない。
Write-Host "Nuitka ビルドを開始します（長時間かかります）..."
& $py -m nuitka `
    --standalone --onefile `
    --assume-yes-for-downloads `
    --output-dir=dist `
    --output-filename=NativeVideoFactory.exe `
    --company-name="Native Video Factory" `
    --product-name="Native Video Factory" `
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
