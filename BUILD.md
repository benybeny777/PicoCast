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
4. **起動時間/サイズ**: onefile は初回展開で起動が遅め・サイズ大。必要なら `--standalone`（フォルダ配布）も検討。
5. **コード署名**: 未署名だと SmartScreen 警告。配布時はコード署名証明書を検討（別途）。
6. **動作確認**: ビルド後、別フォルダ（Python無し相当）で exe を起動し、(a) /setup 表示、(b) settings.db が exe_dir/data に作られる、(c) job-runner が起動する（生成ジョブが進む）、(d) VOICEVOX/ffmpeg 検出、を確認。

## 注意
- 実ビルドは長時間かつ数回の調整が必要なことがある。エラーは上記2〜3の同梱漏れが大半。
- VOICEVOX / ffmpeg / Ollama / Stable Diffusion WebUI は同梱しない（`/setup` の案内から各自DL）。
