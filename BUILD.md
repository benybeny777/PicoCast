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
成果物: `dist\NativeVideoFactory.exe`

`build_exe.ps1` がやること:
1. Nuitka 未導入なら導入
2. `core/_build_version.py` にバージョンを焼き込む（exe では git が使えないため。`.gitignore` 済み）
3. onefile standalone でコンパイル（テンプレート/static/legal/SEED/prompt_profiles/samples/assets を同梱）

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
4. **起動時間/サイズ**: onefile は初回展開で起動が遅め・サイズ大。`build_exe.ps1` は `zstandard` を導入して onefile を圧縮する（未導入だと圧縮スキップ警告＋サイズ増）。さらに小さくしたい/起動を速くしたい場合は `--standalone`（フォルダ配布）も検討。`--include-windows-runtime-dlls=yes` で VC++ ランタイムを同梱している（配布先にランタイムが無くても起動可能）。
5. **コード署名 / ウイルス誤検知**: 未署名だと SmartScreen 警告に加え、Windows Defender が onefile 展開後の `app.dll` を `Program:Win32/Contebrew.A!ml` 等のML ヒューリスティックで**誤検知・隔離**し `Error 225 (load DLL)` で起動失敗することがある（Nuitka/PyInstaller共通の既知の誤検知）。
   - 展開先は `--onefile-tempdir-spec="{CACHE_DIR}\NativeVideoFactory\{VERSION}"` で固定済み（ランダム temp ではなく `%LOCALAPPDATA%\NativeVideoFactory\<version>`）。開発機ではこのフォルダを Defender 除外に追加すれば再ビルドのたびに引っかからない: `Add-MpPreference -ExclusionPath "$env:LOCALAPPDATA\NativeVideoFactory"`（管理者）。
   - 配布時の根本解決は**コード署名（Authenticode）**。署名すると ML 誤検知も SmartScreen も大幅に減る。`--standalone`（フォルダ配布）にすると temp 展開がなくなり誤検知されにくい。必要なら Microsoft へ誤検知申告（https://www.microsoft.com/wdsi/filesubmission ）。
   - **自己署名（開発・既知PC向け）**: `.\make_codesign_cert.ps1` を1回実行すると `CurrentUser\My` に自己署名コード署名証明書を作成し、このPCの信頼ストア（Root / TrustedPublisher）へ登録する。以降 `build_exe.ps1` がビルド後に exe を自動署名する。**ただし公的CAではないため不特定多数配布では無効**。さらに **onefile では外側 exe のみ署名され、展開される app.dll は未署名のまま**なので Defender のML誤検知対策にはならない（その用途は上記の除外/standalone/公的署名）。他PCで「不明な発行元」を消すには `dev/codesign/NativeVideoFactory-public.cer` を相手PCの Root / TrustedPublisher にインポートする（秘密鍵は配らない）。
6. **動作確認**: ビルド後、別フォルダ（Python無し相当）で exe を起動し、(a) /setup 表示、(b) settings.db が exe_dir/data に作られる、(c) job-runner が起動する（生成ジョブが進む）、(d) VOICEVOX/ffmpeg 検出、を確認。

## 注意
- 実ビルドは長時間かつ数回の調整が必要なことがある。エラーは上記2〜3の同梱漏れが大半。
- VOICEVOX / ffmpeg / Ollama / Stable Diffusion WebUI は同梱しない（`/setup` の案内から各自DL）。
