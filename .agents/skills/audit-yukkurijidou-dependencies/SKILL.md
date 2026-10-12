---
name: audit-yukkurijidou-dependencies
description: yukkurijidouのPythonパッケージ（config/requirements*.txt）、Python本体、Nuitka、外部アプリ（VOICEVOX・ffmpeg・SD WebUI・Ollama・AquesTalk）、SDモデル（assets/sd_webui/model_manifest.json）、外部APIのモデル名を、all／packages／apps／models の指定範囲で棚卸しし、公式最新版・互換性・ライセンス・文書まで照合・更新する依頼で使う。
---

# yukkurijidouの外部依存を監査する

## 対象を決める

1. 引数を `all`、`packages`、`apps`、`models` として扱う。省略時は `all` にする。
2. `packages` は `config/requirements.txt`・`config/requirements-dev.txt`、ビルド用の Nuitka・zstandard、Python本体の版（`BUILD.md`・README の記載）を対象にする。
3. `apps` は VOICEVOX、ffmpeg、Stable Diffusion WebUI、Ollama、AquesTalk など利用者が別途導入する外部アプリと、README・SETUP画面で案内している版・取得元を対象にする。
4. `models` は `assets/sd_webui/model_manifest.json` のSDモデルと、`config/config.py` に既定値として置いた Gemini・OpenAI・Ollama などのモデル名を対象にする。

## 棚卸しする

1. 対象ファイルを読み、パッケージ名、版指定の有無、取得URL、`sha256`、ライセンス注記を一覧にする。
2. `rg` で `source_url`、`resolve/main`、`releases/download`、`releases/latest`、`sha256`、`MODEL`、`_MODEL` を再検索し、一覧の漏れを点検する。
3. 版を固定していないパッケージは、現在の環境で解決される版を `pip list --format=freeze`（`.venv` があればその中）で記録する。
4. 大容量モデル・外部アプリの取得処理（`core/sd_model_manager.py` など）の呼び出し元を逆引きし、起動や通常操作が利用者の明示操作なしに大容量取得を始めないか確認する。

## 公式最新版と照合する

1. PyPI、GitHub Releases、Hugging Face、各公式配布元など一次情報だけを使う。
2. 公式LTSまたは長期保守安定版がある場合はLTSを優先し、無い場合は安定版latestを採用対象とする。nightly、preview、RCは明示指示がない限り採用しない。
3. 「最新版の版」と「yukkurijidouが実際に使う・案内する版」を分けて記録する。旧版を維持する場合は固定理由と確認日を記録する。
4. URLが生きているだけで合格にせず、期待するファイル名・サイズ・ハッシュと実体が一致するか確認する。`sha256` が空のモデルは、取得できる場合に値を埋める候補として報告する。
5. Gemini・OpenAI などの外部APIモデル名は公式のモデル一覧・廃止予定表と照合する。廃止予定のモデルは移行先と期限を報告する。費用が発生するAPIを確認のために実行しない（`AGENTS.md`）。
6. ライセンス・商用利用条件が変わっていないか、`license_note` と配布元ページを照合する。

## 更新する

1. 更新は目的別にコミットを分ける（パッケージ・外部アプリ案内・モデル）。
2. パッケージを更新したら `python -m pytest -q` を通す。直接依存のメジャー更新は破壊的変更点を一次情報で確認し、影響箇所を `rg` で列挙する。
3. 外部アプリ・モデルの案内を変えたら、README・SPEC・SETUP画面の記載を同じ作業で同期する。
4. 監査結果（対象、現行版、上流版、更新・見送り理由、未確認事項）を作業報告またはPR本文へ書く。

## 停止条件

- 一次情報から最新版または配布条件を確認できない。
- 更新後に対象OS（Windows / macOS）向けの配布物が存在しない。
- ハッシュ検証していた経路が弱くなる。
- ライセンスまたは商用利用・再配布条件が不明になる。
