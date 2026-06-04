# exe ビルド手順（Nuitka）

配布用の単一exe（onefile）を Nuitka で作るための手順とメモ。
**配布先PCには Python は不要**（exe に同梱）。VOICEVOX / ffmpeg は別途インストール（個別DL方針）。

## ビルド用PCの前提
- Windows + Python 3.11（`.venv` に依存インストール済み）
- Cコンパイラ: MSVC（Visual Studio Build Tools）または Nuitka が自動DLする MinGW64（初回ネット必要）
- Nuitka（`build_exe.ps1` が未導入なら自動で `pip install nuitka`）

## ビルド実行
```powershell
.\build_exe.ps1
```
成果物: `dist\NativeVideoFactory\NativeVideoFactory.exe`（standalone フォルダ一式）。配布はこのフォルダごと（zip / インストーラ）。

`build_exe.ps1` がやること:
1. Nuitka / zstandard 未導入なら導入
2. `core/_build_version.py` にバージョンを焼き込む（HEAD コミット日付ベース）
3. standalone（フォルダ配布）でコンパイル（テンプレート/static/legal/SEED/prompt_profiles/samples/assets を同梱）。`dist\app.dist` を `dist\NativeVideoFactory` にリネーム
4. 自己署名証明書が `CurrentUser\My` にあれば、フォルダ内の未署名バイナリ（Nuitka 生成の exe/dll/pyd）へ署名する（MS 署名済み DLL は上書きしない）

> 署名で Defender のML誤検知を確実に避けるには、先に `.\make_codesign_cert.ps1` を1回実行して証明書を作成・信頼登録しておく。これでこのPC（証明書を信頼登録したPC）では署名済みバイナリが信頼され誤検知されない。

## frozen(exe) 対応として実装済み
- `core/runtime_env.py`: `is_frozen()` / `app_base_dir()`（永続データの基準）/ `resource_base_dir()`（同梱リソースの基準）。
- `core/secret_store.py` / `core/settings_store.py`: `data/settings.db`・マスターキーを `app_base_dir()` 基準に。
  → onefile でも **exe と同じフォルダの `data/`** に永続化（一時展開先に書いて消える問題を回避）。
- `core/channel_profile.py` / `core/output_paths.py` / `config/config.py`: 永続データ（`output/`・チャンネル `settings.db`・`metadata.db`・`DEBUG_LOG_DIR`）の基準を `app_base_dir()` に統一。同梱リソース（`config/prompt_profiles` / `config/SEED`）だけ `resource_base_dir()`（展開先）から読む。
  → onefile でも出力・チャンネルDB・デバッグログが **exe と同じフォルダ** に永続化される（temp展開先に書いて消える問題を回避）。
- 出力ベースは設定 `OUTPUT_BASE_DIR`（設定DB）で別ドライブへ変更可。`/setup` の「出力先フォルダ」で絶対パス指定すれば exe 隣以外にも置ける。
- `web_app/app.py`: job-runner を frozen 時は `exe --run-runner` で起動（`python -m workers.runner` の代替）。`main()` 先頭で `--run-runner` を処理。
- `core/gui_support.py: build_app_version()`: 焼き込み `core/_build_version.py` を最優先。

## 既知の残課題（実ビルド時に確認・対応）
1. **出力先パス**: 対応済み。`output/`・チャンネル `settings.db`・`metadata.db`・`DEBUG_LOG_DIR` は `app_base_dir()`（frozen=exeフォルダ）基準に統一済みで、cwd に依存しない。`config.py` の `OUTPUT_DIR` も `app_base_dir()` 基準の絶対パスへ解決される。別ドライブへ置きたい場合は `/setup`「出力先フォルダ」で `OUTPUT_BASE_DIR` を絶対指定する。
2. **隠れ import**: `uvicorn` のプロトコル実装、`google.genai`、`cryptography`(cffi/openssl)、`pillow`、`keyring`(任意) などが取り込み漏れする場合がある。起動時 ImportError が出たら `--include-module=...` を追記。
3. **uvicorn の import 文字列**: `uvicorn.Config("web_app.app:app")` は文字列参照。エントリが `web_app/app.py` なので通常は同梱されるが、起動失敗時は `--include-module=web_app.app` を明示。
4. **配布形態/サイズ**: standalone はフォルダ配布（`dist\NativeVideoFactory\` ごと zip / インストーラで配る）。onefile より起動が速く（temp 展開なし）、Defender 誤検知も避けやすい。`--include-windows-runtime-dlls=yes` で VC++ ランタイムを同梱（配布先にランタイムが無くても起動可能）。
5. **コード署名 / ウイルス誤検知**: 未署名だと SmartScreen 警告に加え、Windows Defender が Nuitka 生成バイナリ（`app.dll` 等）を `Program:Win32/Contebrew.A!ml` 等のML ヒューリスティックで**誤検知・隔離**することがある（Nuitka/PyInstaller共通）。onefile では展開後の `app.dll` で `Error 225 (load DLL)` 起動失敗になっていた。
   - **standalone＋自己署名で対処（現行）**: `.\make_codesign_cert.ps1` を1回実行 → `CurrentUser\My` に自己署名証明書を作り、このPCの信頼ストア（Root / TrustedPublisher）へ登録。以降 `build_exe.ps1` が `dist\NativeVideoFactory\` 内の未署名バイナリ（exe/dll/pyd）へ署名する。**証明書を信頼登録したPCでは署名済みバイナリが信頼され誤検知されない**（MS 署名済み DLL は上書きしない）。
   - 念のための保険として Defender 除外も可: `Add-MpPreference -ExclusionPath "<dist\NativeVideoFactory のフルパス>"`（管理者）。
   - **不特定多数への配布**: 自己署名は無効。**公的CA（できればEV）のコード署名証明書**が必要。署名すると ML 誤検知も SmartScreen も大幅に減る。必要なら Microsoft へ誤検知申告（https://www.microsoft.com/wdsi/filesubmission ）。
   - 他PCで「不明な発行元」を消すには `dev/codesign/NativeVideoFactory-public.cer` を相手PCの Root / TrustedPublisher にインポート（秘密鍵は配らない）。
6. **動作確認**: ビルド後、`dist\NativeVideoFactory\NativeVideoFactory.exe` を起動し、(a) /setup 表示、(b) settings.db がフォルダ内 `data\` に作られる、(c) job-runner が起動する（生成ジョブが進む）、(d) VOICEVOX/ffmpeg 検出、を確認。

## 注意
- 実ビルドは長時間かつ数回の調整が必要なことがある。エラーは上記2〜3の同梱漏れが大半。
- VOICEVOX / ffmpeg / Ollama / Stable Diffusion WebUI は同梱しない（`/setup` の案内から各自DL）。
