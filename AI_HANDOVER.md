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
- YouTubeアップロード（予約投稿・スケジュール管理）
- 履歴選択、画像確認、再生成

## 重要な最近の変更

### 最新セッション

- **チャンネル方針を食べ物雑学特化へ更新**:
  - チャンネル名: `ずんだもんとめたんの食べ物雑学堂`
  - アニメ雑学系の方向性を削除し、食べ物の歴史・起源・昔の食文化に寄せた
  - `core/vidiq_food_prompt.txt` に台本生成プロンプトを分離し、`build_vidiq_prompt()` から読み込む
- **AIタイトル案コピー機能** (`gui.py`, `core/script_prompts.py`):
  - `AIタイトル案` ボタンを追加
  - 既存の食べ物系タイトルだけを `output/` と `output/uploaded_titles.txt` から収集
  - 既存食材・表記ゆれ・同じオチ・同じタイトル型を避けるタイトル案プロンプトをコピー
  - 出力は20案のMarkdown表 + TOP5のMarkdown表
- **手動公開済みオペレーション** (`gui.py`):
  - `📅 スケジュール` 画面に `手動公開済みにする` を追加
  - YouTube Studio側で予約動画を手動公開した場合、該当スケジュールを削除し `output/uploaded_titles.txt` にタイトルを追記
- **作業中止の即時化** (`gui.py`, `main.py`):
  - `作業中止` 押下でGUIを即 `Canceled` 扱いにして後続処理へ進ませない
  - 生成ごとにキャンセルイベントを分離し、中止後に新しい生成を始めても古い処理が復活しないようにした
  - 画像生成・Batch API・サムネ生成の戻り直後にもキャンセル判定を追加
- **四国めたんのアクション時の目消え対策** (`core/ymmp_editor.py`):
  - めたんの感情差分で目の基本レイヤー `n68` / `n69` を外さないよう変更
  - 表情適用後も `n68` / `n69` を必ず残すガードを追加
- **YouTubeアップロード予約投稿** (`core/upload_scheduler.py` 新規):
  - スロット: 毎日 0:00 / 7:00 / 12:00 / 19:00 (JST)
  - Shorts / Long を**別ファイルで管理**: `output/upload_schedule_shorts.json` / `output/upload_schedule_long.json`
  - 同一スロットに Shorts 1本 + Long 1本の同時予約が可能
  - `assign_slots(count, video_type)` で空きスロットを自動アサイン
  - `mark_slot_used(slot_dt, title, video_type)` でアップロード後に永続保存
- **アップロード確認ダイアログを Treeview 化** (`gui.py`): タイトル・種別・予約日時を表形式で表示
- **スケジュール確認画面** (`gui.py` `show_upload_schedule_dialog()`):
  - 「📅 スケジュール」ボタンから起動
  - 済み（グレー背景）/ 予定（青太字）で色分け
  - 行選択して削除可能
- **`publish_at` パラメータ追加** (`core/youtube_uploader.py`): datetime または ISO8601 文字列を指定すると予約投稿。`privacyStatus` は自動で `"private"` になる
- **`containsSyntheticMedia` を `False` に変更**: 「改変または合成コンテンツ」ラベルを非表示
- **説明文のGemini整形を廃止** (`main.py`): NGワード置換のみ実施し、`_VOICEVOX_CREDIT` + `_CHANNEL_FOOTER` を末尾に固定付与。Gemini整形が CTA や URL を重複させる問題を解消
- **説明文にVOICEVOXクレジット不要** (`core/script_prompts.py`, `core/ai_generator.py`): AI台本の説明文フィールドにクレジットを書かせない。`format_description()` のプロンプトでも削除指示
- **バリデーション強化** (`core/parser.py`):
  - タイトルに改行または100文字超を検出してエラー
  - 履歴からの複数選択時にも、スレッド開始前に全台本を一括バリデーション（`start_generation_from_histories()`）
- **背景画像に人物禁止ルール追加** (`core/image_generator.py`): Shorts・Long 両方のレイアウトルールに「ずんだもん・四国めたんを含むキャラクター描画禁止」を明記
- **デバッグ時に画像プロンプトをファイル保存** (`core/image_generator.py`): `debug=True` のとき `backgrounds/image_prompts.txt` に追記（画面には表示しない）
- **四国めたんの既定手ポーズを普通に変更** (`core/character_templates.json`): YMM4 PSDレイヤーIDで右手 `n16`、左手 `n24` を有効化。目レイヤーはGit版の `n65,n60,n34,n32,n26,n25,n17` 系を維持
- **音声末尾切れ対策** (`main.py`): Shorts / Long 共通で音声アイテムに `VOICE_TAIL_SAFETY_FRAMES = 20` を追加し、次セリフまで `INTER_DIALOGUE_GAP_FRAMES = 25` フレーム空ける

### それ以前

- **台本プロンプト全面刷新** (`core/script_prompts.py`): `build_vidiq_prompt()` を高視聴維持・高テンポ・Shorts特化の新プロンプトに完全置き換え
- **サムネ文字フィールド追加**: 台本に `サムネ文字:` フィールドを追加
- **パーサー強化** (`core/parser.py`): 次行形式のメタデータ対応・`parse_string()` 追加
- **API課金前に全チェック完了**: `gui.py` `start_generation()` で事前バリデーション
- YouTube NGワード置換を追加: `core/ng_words.py`
- 台本作成プロンプトを分離: `core/script_prompts.py`
- `動画形式:` が複数ある入力を複数動画として扱う
- YMM4のセリフ字幕 / 音声を立ち絵より上のレイヤー `6` に変更
- 固定BGMとして BGMer「のほほん」を追加
- GUIから作業中止できるよう `cancel_event` を導入
- 履歴コンボボックスを廃止し、履歴選択ダイアログに統一
- 履歴から複数選択して再生成・アップロードできる
- 画像確認機能（履歴からサムネイル / 背景を確認・再生成）

## 主要ファイル

| ファイル | 役割 |
|---|---|
| `gui.py` | tkinter GUI。履歴選択、一括生成、画像確認、アップロード、スケジュール確認、手動公開済み処理、AIプロンプトコピー |
| `main.py` | パイプライン本体。台本整形、画像/音声生成、YMM4保存 |
| `config.py` | VOICEVOX、モデル、キャラ、BGM、背景生成上限など |
| `core/parser.py` | 台本パーサ |
| `core/ai_generator.py` | Geminiによる台本/メタデータ補助 |
| `core/image_generator.py` | Nano Banana画像生成 |
| `core/voicevox.py` | VOICEVOX API |
| `core/ymmp_editor.py` | YMM4 JSON作成 |
| `core/ymm4_renderer.py` | YMM4 GUI自動操作 |
| `core/youtube_uploader.py` | YouTubeアップロード（予約投稿対応） |
| `core/upload_scheduler.py` | アップロードスケジュール管理（Shorts/Long 別） |
| `core/ng_words.py` | NGワード置換 |
| `core/script_prompts.py` | 台本生成プロンプト |

## YouTubeアップロード・スケジュール

- スロット: 毎日 **0:00 / 7:00 / 12:00 / 19:00 (JST)**
- Shorts と Long は**独立して管理**（同一スロットに両方投稿可）
- 永続化: `output/upload_schedule_shorts.json` / `output/upload_schedule_long.json`
- GUI「📅 スケジュール」ボタン → `show_upload_schedule_dialog()` で一覧・削除・手動公開済み処理
- アップロードフロー:
  1. `start_youtube_upload()` で履歴を複数選択
  2. Shorts/Long 別にスロット自動アサイン
  3. `_confirm_upload_schedule()` で Treeview 確認ダイアログ
  4. `_run_upload_batch()` で順番にアップロード
  5. 成功後: `mark_slot_used()` でスケジュール記録 → `output/000_uploaded/` へ移動

## レイヤー方針

| レイヤー | 用途 |
|---:|---|
| 0 | 背景画像 |
| 1 | トランジション |
| 2 | BGM |
| 3-4 | 立ち絵 |
| 6 | セリフ字幕 / 音声 |

`core/ymmp_editor.py:add_voice_item()` のデフォルトレイヤーは `6`。

## 音声タイミング方針

`main.py` の音声配置:

- VOICEVOX WAV 実長に `character_templates.json` の `AdditionalTime` 0.3 秒相当 (`_ADDITIONAL_FRAMES`) を足す
- さらに `VOICE_TAIL_SAFETY_FRAMES = 20` フレームを音声アイテム長へ加える
- 次セリフ開始までは `INTER_DIALOGUE_GAP_FRAMES = 25` フレーム空ける

この処理は Shorts / Long 共通。

### 音声末尾切れ対策（重要）

**症状**: YMM4 で音声の末尾が切れる（WAV を直接再生すると切れていない）

**原因**: VOICEVOX の `postPhonemeLength` API パラメータが `speedScale=1.5` 環境で効かず、WAV に末尾無音が付加されない。YMM4 が音声アイテムをわずかに早めに終端するため、末尾の音声が途切れる。

**対策**: WAV 生成直後に Python で 0.5 秒分の無音サンプルを WAV に直接追記する（`main.py` 内 `_TAIL_SILENCE_SEC = 0.5`）。`postPhonemeLength` API パラメータは信頼しない。

```python
_TAIL_SILENCE_SEC = 0.5
with wave.open(audio_path, 'rb') as wr:
    sr, ch, sw = wr.getframerate(), wr.getnchannels(), wr.getsampwidth()
    orig_frames = wr.readframes(wr.getnframes())
silence = b'\x00' * (int(sr * _TAIL_SILENCE_SEC) * ch * sw)
with wave.open(audio_path, 'wb') as ww:
    ww.setframerate(sr); ww.setnchannels(ch); ww.setsampwidth(sw)
    ww.writeframes(orig_frames + silence)
```

再発した場合は `_TAIL_SILENCE_SEC` を増やす（0.5 → 0.7 など）。

## 立ち絵PSDレイヤー注意

四国めたんのPSDレイヤーIDは、`metan_layers.txt` の見た目順とYMM4の `n番号` が一致しない。YMM4プロジェクトで使う実IDはPSDレコード順ベース。

- 右手「普通」: `n16`
- 左手「普通」: `n24`
- 旧ポーズ: 右手「指差す」 `n15`、左手「マイク」 `n21`
- 目はGit版を維持: `n65`, `n60`, `n34`, `n32`, `n26`, `n25`, `n17`

`core/character_templates.json` の四国めたん `TachieDefaultItemParameter.EnableLayers` は、通常手として `n16` / `n24` を含める。

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

YouTubeアップロード:

- `start_youtube_upload()` で履歴を複数選択
- `_run_upload_batch()` で順番にアップロード
- 成功後は `_run_upload()` が `output/000_uploaded/` へ移動

作業中止:

- `self.cancel_event`
- `request_cancel()`
- `main.run_pipeline(..., cancel_event=...)`
- ボタン押下時点でGUIは即 `Canceled` 扱いに戻す
- 外部API呼び出し自体は戻るまで待つが、戻り後に成功扱いへ進ませない

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
uv run python -m py_compile config.py main.py gui.py core/parser.py core/voicevox.py core/ymmp_editor.py core/ng_words.py core/script_prompts.py core/upload_scheduler.py
```

必要なら `.uv-cache` は確認してから削除する。
