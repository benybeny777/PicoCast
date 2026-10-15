---
name: audit-nvf-dependencies
description: Native Video Factory の Python パッケージ（config/requirements*.txt）と外部ソフト（VOICEVOX / ffmpeg / Stable Diffusion WebUI / Ollama / Nuitka）を棚卸しし、公式最新版・互換性・ライセンス・文書まで照合して更新する依頼で使う。
---

# 外部依存を監査する

## 対象を決める

1. 引数を `all`、`packages`（Python パッケージ）、`apps`（外部ソフト・ビルドツール）として扱う。省略時は `all`。
2. 外部ソフトは同梱しない方針（個別DL）。監査対象は「案内するダウンロード先と対応版」であり、同梱を提案しない。

## 棚卸しする

1. `config/requirements.txt` / `config/requirements-dev.txt` の固定版と、`.venv` の実際の版（`./.venv/Scripts/python.exe -m pip list --format=freeze`）を突き合わせる。
2. `rg` で `DOWNLOAD_URL`、`releases`、`version`、`MODEL` を `config/config.py` と `core/service_detector.py` から探し、案内URLと既定モデル名を一覧にする。
3. `build_exe.ps1` が導入する Nuitka / zstandard の版を確認する。

## 公式最新版と照合する

1. PyPI、GitHub Releases、各公式配布元など一次情報だけを使う。
2. 安定版 latest を採用対象とし、nightly・preview・RC は明示指示がない限り採用しない。互換性・ライセンス・対象OSに具体的な問題がある場合だけ旧版を維持し、固定理由と確認日を記録する。
3. 「最新版」と「実際に使っている版」を分けて記録する。URL が生きているだけで合格にせず、期待する配布物があることを確認する。
4. ライセンスと再配布条件を確認する。商用利用条件が変わったもの（VOICEVOX キャラクター規約、Stable Diffusion モデル、AquesTalk 等）は利用規約・README への影響を確認する。

## 更新する

1. 更新は目的別コミットに分け、`config/requirements*.txt` の固定版を更新する。
2. `pip install --upgrade -r config/requirements.txt` 後に `./.venv/Scripts/python.exe -m pytest -q` を通す。動画生成に関わるもの（Pillow / numpy / ffmpeg 連携）はサンプル台本で実生成まで確認する。
3. 案内URL・対応版を変えたら README とセットアップ画面の案内（`get_installation_guides()`）を同じ作業で更新する。

## 停止条件

- 一次情報から最新版または配布条件を確認できない。
- 更新後に Windows / macOS 向けの配布物が無い。
- ライセンスまたは商用利用条件が不明になる。

## 報告

`packages` と `apps` を分け、各依存の採用版・最新版・保留理由・未確認事項を書く。
