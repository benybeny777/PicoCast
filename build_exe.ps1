# Native Video Factory — Nuitka exe ビルドスクリプト（Windows）
#
# 既定: 配布用 onefile 単一 exe を dist\NativeVideoFactory.exe に作る。
# -Standalone: フォルダ配布（dist\NativeVideoFactory\）を作る。temp 展開がなく
#              フォルダ内バイナリへ署名できるため Defender 誤検知を避けやすい。
#
# 実行にはビルド用PCに Python + Nuitka + Cコンパイラが必要。
# 配布先PCには Python は不要（同梱）。VOICEVOX / ffmpeg は別途インストール。
#
# 使い方:
#   .\build_exe.ps1              # onefile 単一exe（既定）
#   .\build_exe.ps1 -Standalone  # フォルダ配布
#
# 注意: onefile は起動時に app.dll を temp 展開するため Defender に誤検知されやすい。
#       開発機では make_codesign_cert.ps1 + Defender 除外(%LOCALAPPDATA%\NativeVideoFactory)で回避する。
#       既知の残課題は BUILD.md を参照。
param([switch]$Standalone)

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

# 3. Nuitka ビルド（既定 onefile / -Standalone でフォルダ）
#    --include-data-dir で同梱リソースを含める。VOICEVOX/ffmpeg は同梱しない。
Write-Host ("Nuitka ビルドを開始します（長時間かかります）... モード: " + $(if ($Standalone) { "standalone(フォルダ)" } else { "onefile(単一exe)" }))
$nuitkaArgs = @(
    "--standalone",
    "--assume-yes-for-downloads",
    "--include-windows-runtime-dlls=yes",
    "--nofollow-import-to=PIL.ImageQt",
    "--nofollow-import-to=PIL.ImageTk",
    "--output-dir=dist",
    "--output-filename=NativeVideoFactory.exe",
    "--company-name=Native Video Factory",
    "--product-name=Native Video Factory",
    "--product-version=$numVer",
    "--file-version=$numVer",
    "--include-data-dir=web_app/templates=web_app/templates",
    "--include-data-dir=web_app/static=web_app/static",
    "--include-data-dir=legal=legal",
    "--include-data-dir=config/SEED=config/SEED",
    "--include-data-dir=config/prompt_profiles=config/prompt_profiles",
    "--include-data-dir=config/samples=config/samples",
    "--include-data-dir=assets=assets",
    "--include-package=web_app",
    "--include-package=core",
    "--include-package=workers",
    "--include-package=config",
    "--include-package=uvicorn",
    "--include-package=fastapi",
    "--include-package=starlette",
    "--include-package=jinja2"
)
if (-not $Standalone) {
    # onefile: 単一exe。展開先を固定して Defender 除外を1フォルダで済ませる。
    $nuitkaArgs += "--onefile"
    $nuitkaArgs += "--onefile-tempdir-spec={CACHE_DIR}\NativeVideoFactory\{VERSION}"
}
& $py -m nuitka @nuitkaArgs web_app/app.py
if ($LASTEXITCODE -ne 0) { throw "Nuitka ビルドに失敗しました。BUILD.md の残課題を参照してください。" }

# 署名対象を決める（onefile=単一exe / standalone=フォルダ）
$signSubject = "CN=Native Video Factory Self-Signed"
$signCert = Get-ChildItem Cert:\CurrentUser\My |
    Where-Object { $_.Subject -eq $signSubject -and $_.HasPrivateKey } |
    Select-Object -First 1

if ($Standalone) {
    # フォルダ名を整える（app.dist -> NativeVideoFactory）
    $distSrc = Join-Path $root "dist\app.dist"
    $distDir = Join-Path $root "dist\NativeVideoFactory"
    if (Test-Path $distSrc) {
        if (Test-Path $distDir) { Remove-Item -Recurse -Force $distDir }
        Rename-Item -Path $distSrc -NewName "NativeVideoFactory"
    }
    $exePath = Join-Path $distDir "NativeVideoFactory.exe"
    Write-Host "完了: $exePath"

    # 4. コード署名: フォルダ内の未署名バイナリ（Nuitka 生成の exe/dll/pyd）に署名。
    #    証明書を信頼登録したPCでは署名済みが信頼され Defender 誤検知を回避できる。
    #    MS 署名済み DLL は上書きしない（NotSigned のものだけ）。
    if ($signCert -and (Test-Path $distDir)) {
        Write-Host "コード署名します（自己署名・未署名バイナリのみ）..."
        $targets = Get-ChildItem -Path $distDir -Recurse -Include *.exe, *.dll, *.pyd
        $signed = 0; $skipped = 0; $failed = 0
        foreach ($f in $targets) {
            $cur = Get-AuthenticodeSignature -FilePath $f.FullName
            if ($cur.Status -eq 'NotSigned') {
                $r = Set-AuthenticodeSignature -FilePath $f.FullName -Certificate $signCert -HashAlgorithm SHA256
                if ($r.Status -eq 'Valid') { $signed++ } else { $failed++ }
            } else { $skipped++ }
        }
        if (Test-Path $exePath) {
            Set-AuthenticodeSignature -FilePath $exePath -Certificate $signCert `
                -HashAlgorithm SHA256 -TimestampServer "http://timestamp.digicert.com" | Out-Null
        }
        Write-Host ("署名完了: 新規署名 $signed 件 / 既署名スキップ $skipped 件 / 失敗 $failed 件")
    } else {
        Write-Host "（署名スキップ: 証明書が未作成。署名するには先に .\make_codesign_cert.ps1 を実行してください）"
    }
} else {
    # onefile: 単一 exe
    $exePath = Join-Path $root "dist\NativeVideoFactory.exe"
    Write-Host "完了: $exePath"

    # 4. コード署名: onefile の外側 exe に署名（発行元識別用）。
    #    注意: 展開される app.dll は未署名のままなので Defender のML誤検知対策にはならない。
    #          onefile の誤検知回避は Defender 除外(%LOCALAPPDATA%\NativeVideoFactory) か公的署名。
    if ($signCert -and (Test-Path $exePath)) {
        Write-Host "コード署名します（自己署名）..."
        $sig = Set-AuthenticodeSignature -FilePath $exePath -Certificate $signCert `
            -HashAlgorithm SHA256 -TimestampServer "http://timestamp.digicert.com"
        if ($sig.Status -ne 'Valid') {
            $sig = Set-AuthenticodeSignature -FilePath $exePath -Certificate $signCert -HashAlgorithm SHA256
        }
        Write-Host ("署名ステータス: " + $sig.Status)
    } else {
        Write-Host "（署名スキップ: 証明書が未作成。署名するには先に .\make_codesign_cert.ps1 を実行してください）"
    }
}
