# AI Handover: YMM4 Auto Video Factory

このドキュメントは、次にこのプロジェクトを触るAI/開発者向けの引き継ぎメモです。

## 現在の目的

台本から、ずんだもん / 四国めたんの解説動画用 YMM4 プロジェクトを自動生成する。

対象範囲:

- 台本作成プロンプト
- 台本パースとNGワード置換
- VOICEVOX音声生成
- Nano Banana画像生成
- YMM4 `.ymmp` 組み立て
- YMM4動画出力の自動操作
- YouTubeアップロード
- 履歴選択、画像確認、再生成

## 重要な最近の変更

### 最新セッション
- **台本プロンプト全面刷新** (`core/script_prompts.py`): `build_vidiq_prompt()` を高視聴維持・高テンポ・Shorts特化の新プロンプトに完全置き換え。最優先ルール8項目・禁止事項・理想構成・NGワード対策を包含
- **サムネ文字フィールド追加**: 台本に `サムネ文字:` フィールドを追加。パーサー・メタデータ保存・Geminiプロンプトすべてに対応
- **パーサー強化** (`core/parser.py`):
  - `サムネ文字:` を `thumbnail_text` として認識
  - 値が次行に来る形式（`フィールド名:\n値`）を全フィールドでサポート（タイトル・背景・タグ等）
  - セリフ行・ignoreパターンを誤って値として取り込まないよう保護
  - `parse_string(text)` メソッドを追加（ファイル経由不要）
- **バリデーション強化** (`core/parser.py` `validate()`): 空タイトル・不正タイトル（`[Shorts]`や`動画形式`を含む）・空背景・空セリフ・セリフ数不足を検出
- **API課金前に全チェック完了**:
  - `gui.py` `start_generation()`: 処理開始前に全スクリプトを一括バリデーション
  - `run_pipeline()`: `sanitize_for_youtube()`（Gemini API）より前にバリデーション実施
  - `sanitize` 後の2回目バリデーションを削除（重複のため）
- **説明文Gemini整形をYYM作成プロセスに移動**: 以前はアップロード時に `format_description()` を呼んでいたが、プロジェクト生成時（メタデータ保存前）に変更
- **Shortsサムネイルを1フレームに変更**: `editor.add_image_item(thumb_path, 0, 1)` （以前は3フレーム）
- **音声速度を1.5倍に変更**: `config.VOICE_SPEED_SCALE = 1.5`（以前は1.3）
- ルートの `script.txt`（不要な残骸）を削除

### それ以前
- YouTube NGワード置換を追加: `core/ng_words.py`
- 台本作成プロンプトを分離: `core/script_prompts.py`
- 台本中のコードフェンスや `━━ 動画1 ━━` 見出しを無視 / 分割できるようにした
- `動画形式:` が複数ある入力を複数動画として扱う
- セリフの後に `背景:` が来る台本を `main.normalize_background_order()` で補正
- 背景は展開変更時だけ入れる方針にプロンプトを調整済み
- YMM4のセリフ字幕 / 音声を立ち絵より上のレイヤー `6` に変更
- 固定BGMとして BGMer「のほほん」を追加
- GUIから作業中止できるよう `cancel_event` を導入
- 履歴コンボボックスを廃止し、履歴選択ダイアログに統一
- 履歴選択時に最終更新日時を表示
- 履歴から複数選択して再生成できる
- YouTubeアップロードも履歴から複数選択できる
- 画像確認機能を取り込み、履歴から対象を選んでサムネイル / 背景を確認・再生成できる

## 主要ファイル

| ファイル | 役割 |
|---|---|
| `gui.py` | tkinter GUI。履歴選択、一括生成、画像確認、アップロード、キャンセル |
| `main.py` | パイプライン本体。台本整形、画像/音声生成、YMM4保存 |
| `config.py` | VOICEVOX、モデル、キャラ、BGM、背景生成上限など |
| `core/parser.py` | 台本パーサ |
| `core/ai_generator.py` | Geminiによる台本/メタデータ補助 |
| `core/image_generator.py` | Nano Banana画像生成 |
| `core/voicevox.py` | VOICEVOX API |
| `core/ymmp_editor.py` | YMM4 JSON作成 |
| `core/ymm4_renderer.py` | YMM4 GUI自動操作 |
| `core/youtube_uploader.py` | YouTubeアップロード |
| `core/ng_words.py` | NGワード置換 |
| `core/script_prompts.py` | 台本生成プロンプト |

## レイヤー方針

| レイヤー | 用途 |
|---:|---|
| 0 | 背景画像 |
| 1 | トランジション |
| 2 | BGM |
| 3-4 | 立ち絵 |
| 6 | セリフ字幕 / 音声 |

`core/ymmp_editor.py:add_voice_item()` のデフォルトレイヤーは `6`。

## BGM

固定BGM:

- 配布元: BGMer「のほほん」
- 保存先: `assets/bgm/nohohon_long_BPM97.mp3`
- 設定: `config.BGM_PATH`, `config.BGM_VOLUME`, `config.BGM_LAYER`
- 追加処理: `main._add_fixed_bgm()`

BGMファイルがない場合は警告ログだけ出して処理を続行する。

## GUIメモ

履歴選択は `YMM4AutoGui.select_history_dialog()` に集約。

- `multi=True` で複数選択
- 最終更新日時を表示
- `script.txt` / 画像 / MP4 の有無を表示

画像確認:

- `start_image_review()`
- `_collect_image_review_specs()`
- `confirm_images_bulk()`
- `regenerate_review_images()`

YouTubeアップロード:

- `start_youtube_upload()` で履歴を複数選択
- `_run_upload_batch()` で順番にアップロード
- 成功後は `_run_upload()` が `output/000_uploaded/` へ移動

作業中止:

- `self.cancel_event`
- `request_cancel()`
- `main.run_pipeline(..., cancel_event=...)`

## 生成パイプラインメモ

`main.run_pipeline()` の流れ:

1. 出力ディレクトリ準備
2. 台本メタデータ抽出
3. `normalize_background_order()`
4. `merge_telops_into_backgrounds()`
5. サムネイル生成
6. 背景生成または再利用
7. VOICEVOX音声生成
8. 背景/音声/立ち絵/字幕/BGMを YMM4 に配置
9. `.ymmp` 保存

背景再利用時は、既存 `backgrounds/` を一時退避して復元する。空フォルダを誤って「再利用あり」と扱わないよう修正済み。

## 注意点

- `output/` は `.gitignore` 対象。
- `.env`, `client_secrets.json`, `token.json` も Git 管理外。
- YMM4のGUI自動操作は環境依存がある。動かない場合は `core/ymm4_renderer.py --inspect` でUI要素名を確認する。
- ドキュメントはUTF-8で更新済み。過去の文字化け版には戻さない。

## 確認コマンド

```bash
uv run python -m py_compile config.py main.py gui.py core/parser.py core/voicevox.py core/ymmp_editor.py core/ng_words.py core/script_prompts.py
```

必要なら `.uv-cache` は確認してから削除する。
