# ずんかみ自動生成システム 仕様書

チャンネル: [ずんだもんとめたんの食べ物雑学堂](https://www.youtube.com/@zunkami)  
最終更新: 2026-05-22（続き）

---

## 概要

食べ物雑学ゆっくり解説動画（Shorts / Long）を自動生成してYouTubeにアップロードするシステム。

- **台本生成** → Gemini AI
- **音声生成** → VOICEVOX (ずんだもん / 四国めたん)
- **背景画像生成** → Nano Banana (Gemini画像生成)
- **動画組立** → YMM4 (.ymmpファイル生成)
- **品質レビュー** → ローカルルール + Ollama LLM + ChatGPT
- **アップロード** → YouTube Data API v3

---

## 開発運用メモ

- コミットメッセージは、基本的に日本語で書く。
- `feat` / `fix` / `docs` / `chore` など、日本人でもすぐ分かる短い英語プレフィックスは使ってよい。
- 例: `feat: 固定コメント投稿画面を追加`、`fix: 非公開動画へのコメント投稿をスキップ`、`docs: 運用ルールを追記`
- 運用や品質に影響する大きめの変更は [CHANGELOG.md](CHANGELOG.md) に残す。
- アプリのタイトルバーにはGitのコミット数・短縮ハッシュを自動表示する。未コミット変更がある場合は `dirty` を付ける。

---

## システム構成

```
yukkurijidou/
├── gui.py                  # Tkinter GUI (メインウィンドウ)
├── main.py                 # 動画生成パイプライン
├── config.py               # 設定・定数
├── core/
│   ├── ai_generator.py     # Gemini台本生成
│   ├── voicevox.py         # VOICEVOX音声生成
│   ├── image_generator.py  # Nano Banana背景画像生成
│   ├── parser.py           # 台本パーサー (ScriptParser)
│   ├── ymmp_editor.py      # YMM4プロジェクト編集
│   ├── native_renderer.py  # ffmpeg/native MP4レンダラー
│   ├── opening_quality.py  # 冒頭品質レビュー
│   ├── script_prompts.py   # 台本生成プロンプト (Python)
│   ├── script_generation_prompt.txt  # 台本生成プロンプト (テキスト)
│   ├── prompt_parts/       # タイトル/台本プロンプトの差し込み部品
│   │   ├── title_dynamic_context_food.md    # 実績データ差し込み欄
│   │   ├── title_duplicate_context_food.md  # 既存タイトル・既存食材の重複チェック
│   │   ├── title_used_foods_food.txt        # 初期食べ物用の既存食材リスト
│   │   └── local/           # 個人用差し替え欄（Git管理外・同名ファイル優先）
│   ├── analytics_score.py  # YouTube Analytics評価・TSV保存
│   ├── youtube_analytics.py # YouTube Analytics API取得
│   ├── upload_scheduler.py # アップロードスケジュール管理（schedule_from_recordsで台帳から派生）
│   ├── upload_records.py   # アップロード台帳の読み書き・upsert
│   ├── output_paths.py     # 出力パスの集約・マイグレーション
│   ├── youtube_uploader.py # YouTube APIアップロード
│   └── ng_words.py         # NGワード置換
├── samples/
│   ├── prompt_parts/food/   # 食べ物用プロンプト設定の復元サンプル
│   └── scripts/             # 共有用サンプル台本
└── output/                 # 生成物出力先
```

`core/script_prompts.py` は `core/prompt_parts/local/` に同名ファイルがある場合、Git管理側の `core/prompt_parts/` より `local/` を優先して読み込む。これにより初期状態は食べ物用設定で動き、別ジャンル担当者は自分の `local/` だけを編集できる。

---

## 動画フォーマット

### Shorts
- 尺: **38〜50秒（理想）/ 35〜55秒（許容）**
- セリフ数: **24〜27行を基本**（22〜28行は許容、31行以上禁止）
- セリフ本文の文字数: **280〜330文字を目標 / 260文字未満は禁止**（背景・テロップ・メタ情報は含めない。21行・190文字前後はnative実尺で短くなりやすい）
- 1セリフ: **原則11〜15文字 / 平均11.5文字以上**（10文字以下は最大4行、7文字以下は原則禁止）
- 尺計算式（native）: `各セリフ本文の文字数 ÷ (5.4 × 音声速度) + 0.1 × 音声速度 = 推定尺`
- 背景枚数: 6〜9枚
- 再生速度（YMM4）: イントロ2.0x（最初5秒）/ 本編1.65x
- 再生速度（native）: イントロ1.40x / 本編1.25x
- アップロードスロット: 毎日 7:00 / 12:00 / 19:00 (JST)

### Long
- 尺: **5〜10分（理想5〜8分）**
- セリフ数: 150〜250行
- 背景枚数: 5〜7秒に1枚（同一背景10秒以上禁止）
- 再生速度（YMM4）: イントロ1.6x / 本編1.35x
- 再生速度（native）: イントロ1.40x / 本編1.20x
- アップロードスロット: 毎日 21:00 / 土日は追加で 12:00 (JST)

---

## 動画生成パイプライン (`main.py: run_pipeline`)

### 全体フロー

```
1. 出力ディレクトリ準備
2. 台本保存
3. 台本パース (ScriptParser)
4. メタデータ抽出 (タイトル / サムネ文字 / 説明文 / タグ / 固定コメント)
5. 冒頭品質レビュー
   ├── ローカルルールベース
   ├── Ollamaレビュー（スコア<70または重大エラーありの場合）
   └── 必要に応じてOllamaリライト → 再パース
6. 冒頭スコアが重大エラー基準未満、または `must_fix` ありなら処理中止 (デフォルト70点)
7. 生成前の尺推定 + 尺レビュー
8. ChatGPT生成前レビュー（評価のみ、修正なし）
   └── `must_fix` あり、または重大エラー基準未満なら処理中止
9. VOICEVOX音声生成（セリフ1行ずつ）
10. 背景画像生成（Nano Banana）
   └── 再利用チェック: 台本変更で枚数が変わる場合は全再生成
11. サムネイル生成（Nano Banana）
12. YMM4プロジェクト組立 (.ymmp)
13. BGM追加
14. YMM4プロジェクト保存
15. 実尺レビュー + 完了レポート
```

### 尺推定 (gui.py: `_estimate_duration`)

```python
CHARS_PER_SEC_AT_1X = 5.4
INTRO_SPEED = 2.0   # 最初5秒
BODY_SPEED = 1.65   # 本編
ADDITIONAL = 0.3 + 0.5 + 0.2  # クロスフェード + 末尾無音 + 行間

elapsed = 0.0
for item in dialogue_items:
    chars = len(item["text"])
    speed = INTRO_SPEED if elapsed < 5.0 else BODY_SPEED
    line_time = chars / (CHARS_PER_SEC_AT_1X * speed) + 0.1 * speed + ADDITIONAL
    elapsed += line_time
```

### 背景再利用ロジック

- 既存の `bg_XXXX.png` がある場合は再利用
- **台本変更により必要な背景枚数が変わった場合**: 既存の背景（サムネ除く）を全削除して再生成

---

## 品質レビュー (`core/opening_quality.py`)

### 冒頭レビュー 3段階

| ステップ | 内容 | 条件 |
|---|---|---|
| ローカルルールベース | 意外性ワード・食べ物名・掛け合い・セリフ長チェック | 常時実行 |
| Ollamaレビュー | `qwen3:8b` でLLMスコアリング | ローカルスコア < 70 または重大エラーあり |
| Ollamaリライト | 冒頭セリフを自動修正 | `should_auto_rewrite_opening` = True |

### `should_auto_rewrite_opening` の条件（いずれか）

- `must_fix` に項目がある
- `hook < 75` / `loop < 70` / `cta < 70`
- 総合スコア < `OPENING_SCORE_HARD_ABORT_THRESHOLD`（デフォルト70）

### 処理中止条件

冒頭スコアが `OPENING_SCORE_HARD_ABORT_THRESHOLD`（デフォルト70）未満、または `must_fix` / 重大エラーあり → パイプライン中止。

`OPENING_SCORE_ABORT_THRESHOLD`（デフォルト80）は、ログ表示上の「pass / warning」判定の目安として使う。70〜79点は警告扱いだが、重大エラーがなければ処理を続行する。

### ChatGPT生成前レビュー

- モデル: `OPENAI_FINAL_REVIEW_MODEL`（デフォルト `gpt-5.2`）
- 入力: タイトル / サムネ文字 / 固定コメント / 台本 / 各レビュー結果 / 推定尺
- 出力: `final_score` / `publish_ok` / `risk` / `must_fix` / `nice_to_fix`
- **自動修正なし** — ログ表示と `_meta/final_review.json` 保存のみ
- `must_fix` がある場合、または `final_score` が `OPENING_SCORE_HARD_ABORT_THRESHOLD` 未満の場合は、音声・画像生成へ進まず中止する
- `render_engine` を入力に含め、native Shorts では「31行以上のみ must_fix」の基準で判定させる（22〜28行は可、24〜27行は理想）
- ChatGPT 応答に旧 YMM4 基準由来の「21行以上 must_fix」が返ってきた場合、native かつ dialogue_count <= 28 なら自動で除去する
- 冒頭1行目の食べ物名チェック: タイトル由来キーワードだけでなく `FOOD_HINT_WORDS`（コーヒー・コーラ・牛乳・紅茶等の飲み物を含む）が初行に直接あればOKとする。N選型は初行に代表食材1つがあればOK（全食材の列挙は不要）

### 保存ファイル（`_meta/` 配下）

| ファイル | 内容 |
|---|---|
| `opening_review.json` | ローカル・Ollamaレビュー結果、final_score、final_status |
| `opening_rewrite_suggestion.txt` | Ollamaリライト内容（リライトが発生した場合） |
| `duration_review.json` | 尺レビュー結果（seconds / status / ideal） |
| `final_review.json` | ChatGPT生成前レビュー結果 |

### LLMレビューの有効化

デフォルトはLLMレビュー有効（`OPENING_REVIEW_USE_LLM=1`）。冒頭LLMレビューと冒頭リライトはローカルの Ollama を使う。無効化する場合は `.env` で `OPENING_REVIEW_USE_LLM=0` を設定する。

```text
OPENING_REVIEW_USE_LLM=1
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_REVIEW_MODEL=qwen3:8b
OLLAMA_REWRITE_MODEL=qwen3:8b
OLLAMA_REWRITE_FALLBACK_MODEL=gemma4:e4b
```

Ollamaに接続できない場合、誤通過防止のため冒頭レビュー段階で処理を中止する。ChatGPT生成前レビューは別系統で、`OPENAI_FINAL_REVIEW_ENABLED` / `OPENAI_FINAL_REVIEW_MODEL` を使う。

---

## Ollamaレビュースキーマ

```json
{
  "overall_score": 78,
  "publish_ok": true,
  "rewrite_recommended": true,
  "must_fix": [],
  "warnings": ["冒頭の意外性はあるが3秒以内の引きがやや弱い"],
  "scores": {
    "hook": 82,
    "title_match": 90,
    "tempo": 76,
    "clarity": 85,
    "loop": 72,
    "cta": 70
  },
  "fix_target": "hook"
}
```

### スコア採点基準（Ollamaに渡す指示）

| 範囲 | 評価 |
|---|---|
| 90〜100 | そのまま出せる強い台本 |
| 80〜89 | 出せるが軽微な改善あり |
| 70〜79 | 弱点あり、修正推奨 |
| 60〜69 | 伸びにくい、修正必須 |
| 59以下 | 作り直し候補 |

---

## アップロードスケジューラー (`core/upload_scheduler.py`)

| 種別 | スロット | 日程 |
|---|---|---|
| Shorts | 7:00 / 12:00 / 19:00 | 毎日 |
| Long | 21:00（毎日）/ 12:00（土日のみ） | 毎日 |

- スロット割当範囲: 最大90日先まで探索
- アップロード実行後: 各動画フォルダの `_meta/upload_record.json` に記録
- スケジュールの正は YouTube Data API の `privacyStatus` / `publishAt`。`schedule_from_youtube()` / `rebalance_slots()` はYouTube側の予約状態を参照する。旧 `upload_schedule_*.json` と中央 `upload_records.json` は廃止
- `sync_schedule_from_youtube()`: YouTube API を正として、必要に応じて各動画のアップロード記録へ反映する。チャンネル全件取得（`get_channel_upload_video_statuses`）に失敗した場合は既知 video_id のみでフォールバック
- `infer_video_type()`: タイトルプレフィックス優先。タイトルなしの場合は duration ≤ 60s を shorts と推定

### 出力データディレクトリ

| パス | 用途 |
|---|---|
| `output/000_data/uploaded_titles.txt` | 公開済みタイトル一覧 |
| `output/000_analytics/` | Analytics スコア JSON / TSV |
| `output/000_legacy/` | 旧 `upload_schedule_*.json` の退避先 |

パスは `config.py` の `OUTPUT_DATA_DIR` / `OUTPUT_ANALYTICS_DIR` / `OUTPUT_LEGACY_DIR` で変更可能。`core/output_paths.py` がこれらを絶対パスに解決して各モジュールへ提供する。

---

## GUI (`gui.py`)

### 主要タブ・機能

| 機能 | 説明 |
|---|---|
| 生成 | 貼り付けた台本から音声・背景・サムネ・YMM4プロジェクトを生成 |
| 作業中止 | 実行中の生成処理に中止リクエストを送る |
| LLM/尺チェック | 複数台本を先に冒頭品質・推定尺・最終品質レビューする |
| AI台本作成 | 既存タイトル重複を避ける台本生成プロンプトをコピー（生成区分・元動画・目的フィールド含む） |
| Shortsタイトル案 / Longタイトル案 | 既存タイトル・Analytics実績データを反映したタイトル案プロンプトをコピー |
| 履歴から複数生成 | 過去生成済みテーマを複数選択して再生成 |
| 画像確認 | サムネイル・背景画像を確認し、選択した画像だけ再生成 |
| YouTubeアップ | 複数動画の一括スケジュールアップロード |
| 固定コメント | アップロード済み動画へ固定コメント用コメントを投稿し、動画URLを表示 |
| スケジュール | 予約中＋直近90日の公開済み動画一覧。公開日時は YouTube API 同期値（`published_at`）を表示。Shorts/Long・予定/公開済みで絞り込み可 |
| アナリティクス | YouTube Analytics取得、横展開候補や改善対象を評価 |
| サービス確認 | VOICEVOX / Nano Banana 起動状態チェック |

### ログカラー

| タグ | 色 | 用途 |
|---|---|---|
| info | #00d8d6 | 通常情報 |
| success | #05c46b | 成功 |
| warning | #ffa502 bold | 警告 |
| error | #ff5e57 | エラー |
| batch | #ef57ff bold | バッチ処理 |
| score | #ffd32a bold 11pt | スコア表示 |
| duration | #34ace0 bold 11pt | 尺情報 |

### Shorts尺アラート（6段階）

| 推定尺 | 色 |
|---|---|
| < 35秒 | 赤 (error) |
| 35〜38秒未満 | 緑 (success) ← やや短いがOK |
| 38〜50秒 | 緑 (success) ← 理想 |
| 50〜55秒 | 黄 (warning) |
| 55〜58秒 | 橙 (warning) |
| > 58秒 | 赤 (error) |

### 事前チェック (`_pre_generate_check`)

エラー（中止）:
- タイトル未設定

警告（ログのみ）:
- サムネ文字が15文字超
- 背景枚数が少ない
- 最初のセリフが8文字未満

### アップロード確認ダイアログ

- 列: 番号 / タイトル / スケジュール / スコア（冒頭 / 尺 / 最終）
- 幅: 860px

---

## VOICEVOX音声生成 (`core/voicevox.py`)

- API: `/audio_query` → `/synthesis` を1行ずつ個別呼び出し
- `postPhonemeLength`: `VOICE_POST_PHONEME_LENGTH`（デフォルト0.0）を VOICEVOX API に渡す
- 末尾無音: 生成後のWAVへ `max(0.1, 0.1 × speed_scale)` 秒の無音を直接追加
- キャラクター・スピーカーID:

| キャラ | スタイル | ID |
|---|---|---|
| ずんだもん | ノーマル | 3 |
| ずんだもん | あまあま | 1 |
| ずんだもん | ツンツン | 7 |
| ずんだもん | セクシー | 5 |
| ずんだもん | ささやき | 22 |
| 四国めたん | ノーマル | 2 |
| 四国めたん | あまあま | 0 |
| 四国めたん | ツンツン | 6 |
| 四国めたん | セクシー | 4 |
| 四国めたん | ささやき | 36 |

### 音声タイミング

Shorts / Long ともに、VOICEVOX の WAV 実長へテンプレートの `AdditionalTime` 0.3 秒を加え、さらに `VOICE_TAIL_SAFETY_SEC = 0.5` 秒を音声アイテム長に足します。次のセリフ開始までは `INTER_DIALOGUE_GAP_SEC = 0.2` 秒空けます。

WAV 末尾には `max(0.1, 0.1 × speed_scale)` 秒の無音を直接書き込みます（Shorts 冒頭 2.0x なら 0.2秒）。高速音声で末尾フォネームが切れるのを防ぎます。

---

## 台本フォーマット

### Shortsフォーマット例

```
動画形式: Shorts
動画タイトル: チョコは500年間ずっと飲み物だった
サムネ文字: 飲み物
説明文: チョコレートの驚きの歴史を解説！
タグ: ずんだもん,ゆっくり解説,VOICEVOX,...
固定コメント: チョコレートが飲み物だった時代、飲んでみたかった？

# Scene 1: Opening hook
背景: 漫画風イラスト調。人物禁止。「飲み物」を白文字・極太黒縁で配置。
テロップ: 飲み物
ずんだもん(ノーマル): チョコは薬だったのだ！
四国めたん(ツンツン): えっ、薬ですの？
```

### Longフォーマット（追加要素）

```
動画形式: Long
チャプター: 1.イントロ / 2.起源 / 3.広まった理由 / 4.まとめ
```

---

## 設定 (`config.py`)

| 設定 | デフォルト | 説明 |
|---|---|---|
| `VOICEVOX_URL` | `http://localhost:50021` | VOICEVOX API URL |
| `VOICE_SPEED_SCALE_SHORTS` | 1.65 | Shorts本編再生速度（YMM4） |
| `VOICE_INTRO_SPEED_SCALE_SHORTS` | 2.0 | Shortsイントロ再生速度（YMM4） |
| `VOICE_INTRO_FAST_SECONDS` | 5.0 | イントロ高速区間（秒） |
| `VOICE_SPEED_SCALE_LONG` | 1.35 | Long本編再生速度（YMM4） |
| `VOICE_INTRO_SPEED_SCALE_LONG` | 1.6 | Longイントロ再生速度（YMM4） |
| `NATIVE_SHORTS_BODY_VOICE_SPEED` | 1.25 | Shorts本編再生速度（native） |
| `NATIVE_SHORTS_INTRO_VOICE_SPEED` | 1.40 | Shortsイントロ再生速度（native） |
| `NATIVE_LONG_BODY_VOICE_SPEED` | 1.20 | Long本編再生速度（native） |
| `NATIVE_LONG_INTRO_VOICE_SPEED` | 1.40 | Longイントロ再生速度（native） |
| `NATIVE_SHORTS_ESTIMATE_BASE_CPS` | 5.4 | Shorts native推定の基準文字/秒 |
| `NATIVE_SHORTS_CHARS_MUST_FIX_MIN` | 260 | Shorts native文字数 must_fix 下限 |
| `NATIVE_SHORTS_TARGET_CHARS_MIN` | 280 | Shorts native文字数 目標下限 |
| `NATIVE_SHORTS_TARGET_CHARS_MAX` | 330 | Shorts native文字数 目標上限 |
| `NATIVE_SHORTS_AVG_CHARS_MIN` | 11.5 | Shorts native平均文字数 必須下限 |
| `NATIVE_SHORTS_SHORT_LINE_MAX` | 4 | 10文字以下の短文セリフ 許容上限 |
| `NATIVE_SHORTS_LINES_IDEAL_MIN` | 22 | Shorts nativeセリフ数 理想下限 |
| `NATIVE_SHORTS_LINES_IDEAL_MAX` | 28 | Shorts nativeセリフ数 理想上限 |
| `NATIVE_SHORTS_LINES_TARGET_MIN` | 24 | Shorts nativeセリフ数 目標下限 |
| `NATIVE_SHORTS_LINES_TARGET_MAX` | 27 | Shorts nativeセリフ数 目標上限 |
| `NATIVE_SHORTS_LINES_WARNING` | 29 | Shorts nativeセリフ数 warning閾値 |
| `NATIVE_SHORTS_LINES_MUST_FIX` | 31 | Shorts nativeセリフ数 must_fix閾値 |
| `DEFAULT_SHORTS_RENDER_ENGINE` | `native` | Shortsのデフォルトレンダラー（native/ymm4） |
| `GENERATE_YMM4_PROJECT` | `true` | native時でもYMM4プロジェクトを生成するか |
| `RENDER_WITH_YMM4` | `false` | YMM4による本番動画書き出しを行うか |
| `VOICE_INTRO_FAST_MODE` | `line_count` | 冒頭速度切り替えモード（line_count/seconds） |
| `VOICE_INTRO_FAST_LINES` | 3 | native: 冒頭N行がintro速度 |
| `GEMINI_MODEL` | `gemini-3.1-pro-preview` | 台本生成モデル |
| `OLLAMA_REVIEW_MODEL` | `qwen3:8b` | 冒頭レビューモデル |
| `OLLAMA_REWRITE_MODEL` | `qwen3:8b` | 冒頭リライトモデル |
| `OPENAI_FINAL_REVIEW_MODEL` | `gpt-5.2` | ChatGPT生成前レビューモデル |
| `OPENING_SCORE_ABORT_THRESHOLD` | 80 | pass / warning 表示の目安 |
| `OPENING_SCORE_HARD_ABORT_THRESHOLD` | 70 | 処理中止スコア閾値 |
| `MAX_BACKGROUNDS_SHORTS` | 9 | Shorts最大背景枚数 |
| `MAX_BACKGROUNDS_LONG` | 90 | Long最大背景枚数（通常モード） |
| `MAX_BACKGROUNDS_LONG_BUDGET` | 16 | Long節約モードの最大背景生成枚数 |
| `LONG_UPLOAD_PLAYLIST_NAME` | `ロング動画` | Longアップロード後に自動追加する再生リスト名。空なら無効 |
| `BGM_VOLUME` | 15.0 | BGM音量(%) |

---

## ffmpeg ネイティブレンダラー (`core/native_renderer.py`) — Shorts本番レンダラー

Shorts の本番レンダラー。通常の「生成」ボタンで Shorts を生成すると自動的に native が選択される。

- **デフォルト動作**: `DEFAULT_SHORTS_RENDER_ENGINE = "native"` が設定されているため、Shorts の `run_pipeline()` は `native_render=None` を受け取ると自動で `native_render=True` に切り替わる。
- `run_pipeline()` は native/YMM4 どちらでも通常通り `.ymmp` プロジェクトを生成する（保険・確認・再編集用）。
- `render_native_test(output_dir, voice_speed_intro, voice_speed_body)` が音声・背景を結合して `{履歴フォルダ名}_native.mp4` を出力する。固定ファイル名のため再生成時は上書き。
- YouTubeアップロード時は履歴フォルダ内の最新MP4を優先して選択する。
- **Shorts のみ**: `thumbnails/thumbnail.png` がある場合、native MP4 の先頭1フレームにサムネイル画像を挿入する（Long は挿入しない）。
- `_meta/render_info.json` に render_engine・voice_speed・line_rule・ymm4_project_generated を保存する。

`DEFAULT_SHORTS_RENDER_ENGINE=ymm4` (.env) で YMM4 本番レンダリングに戻せる。

### 安定条件（YMM4 とは別基準）

| 項目 | YMM4 | native |
|---|---|---|
| Shorts セリフ数（理想） | 17〜20行 | 24〜27行（22〜28行は許容） |
| Shorts セリフ数（warning） | 20行（21+ は must_fix） | 29〜30行 |
| Shorts セリフ数（must_fix） | 21行以上 | 31行以上 |
| Shorts 推定尺チェック | 35s未満または55s超で停止 | 参考値のみ表示（停止しない） |
| Shorts 音声速度 | イントロ 2.0x / 本編 1.65x | イントロ 1.40x / 本編 1.25x |
| Long 音声速度 | イントロ 1.6x / 本編 1.35x | イントロ 1.40x / 本編 1.20x |

native では尺ではなく**語り速度（chars/sec）と台本量**で調整するため、推定尺による停止は行わない。

### 実尺チェック（native MP4 生成後）

`render_native_test()` 完了後、`gui.py` が ffprobe で計測した MP4 の実尺に対して `duration_review()` を実行し、YMM4 パスと同じ基準で判定を表示する。

```
━━━━━━━━ 実尺チェック 44.3秒 / 理想（38〜50秒） ━━━━━━━━   ← 緑
━━━━━━━━ 実尺チェック 53.1秒 / OKだけど長め ━━━━━━━━      ← 黄
━━━━━━━━ 実尺チェック 60.2秒 / 要確認 ━━━━━━━━            ← 赤
```

- 結果は `_meta/duration_review.json` に `"source": "native_mp4"` 付きで上書き保存する
- 判定基準は YMM4 パスと共通（ideal: 38〜50s / ok_but_short: 35〜37s / ok_but_long: 51〜55s / warning: 32〜34s or 56〜58s / needs_review: それ以外）

### 詳細ログ（`render_native_test` 完了時）

```
📊 render_engine: native
   voice_speed_intro: 1.40 / voice_speed_body: 1.25
   dialogue_lines: 25 / script_chars: 420
   audio_duration_total: 52.3秒 / silence_total: 4.80秒 / median_silence: 0.20秒
   speech_chars_per_sec: 8.02 / final_video_duration: 57.1秒
   速度判定: Shorts向きで良い / 台本量判定: OK
```

### native字幕の可読性

Shortsの通常字幕は、背景に左右されない可読性を最優先する。本文は白文字で統一し、話者差は文字色ではなくフチ色で表現する。

- ずんだもん: 白文字 + 濃緑の内フチ + 黒外フチ
- 四国めたん: 白文字 + 濃ピンク紫の内フチ + 黒外フチ
- 背景が複雑な場合でも読めるよう、Shortsでは半透明黒帯を背面に出せる
- 黒帯を使う場合もキャラ色フチは残し、V13相当のキャラ色の印象と可読性のバランスを取る
- 黄緑・赤・黄色などの色付き字幕は全文ではなく重要語の強調に限定する

---

## Long動画専用機能

### サムネイルA/Bテスト

GUI オプション行の **「LongサムネAB」チェックボックス**（デフォルト OFF）または `config.py` の `LONG_THUMBNAIL_AB_TEST` で制御。GUI の設定が優先される。

- **OFF（デフォルト）**: Variant A のみ生成。`thumbnail_ab_test.json` は書かない。
- **ON**: 3バリアントを生成し `_meta/thumbnail_ab_test.json` で管理。
  - **Variant A**: 食べ物クローズアップ（クリック重視）
  - **Variant B**: 古い歴史・驚き演出
  - **Variant C**: 昔と今の比較・ギャップ

YouTube Data APIでは公式A/Bテストを開始できないため、A/B/C案はPC版YouTube Studioで手動登録します。通常アップロードではA案だけを `thumbnail.png` としてAPI設定します。アップロード後は動画IDを `thumbnail_ab_test.json` に記録し、`<video_id>_thumbnail_A/B/C.png` 形式のコピーも保存します。

### タイトルA/Bテスト

`_meta/title_ab_test.json` でタイトルバリアントを管理（手動切り替え）。YouTube APIアップロード時はA案タイトルを既定として使い、B/C案はYouTube Studioで手動テスト。

### 画像 SD 生成モード

GUI オプション行の **「SD生成」チェックボックス**（デフォルト OFF）で制御。Shorts / Long 両方に適用される。

ON にすると `SD_SIZE_IMAGE_SCALE`（デフォルト 0.5、`.env` で変更可）倍の小サイズで画像を生成し、元の解像度に拡大してセットする。API トークン消費とコストを削減できる反面、解像度が粗くなる。通常生成・画像確認再生成・サムネイル再生成の全パスに適用される。

### Long画像節約モード

GUI オプション行の **「Long節約」チェックボックス**（デフォルト OFF）で制御。Shorts には影響しない。

| モード | 最大新規生成数 | 用途 |
|--------|-----------|------|
| 通常（OFF） | 90枚 | 全シーン個別生成 |
| 節約（ON） | 16枚 | コスト削減 |

**上限超過時の動作**: 設定枚数を超えたシーンは前の背景をそのまま継続使用する。

**明示的再利用記法**: 台本で `背景: 前と同じ` と書いたシーンはカウントを消費せずに前の背景を継続する。重要シーン（冒頭・章タイトル・対比・オチ）に新規生成を集中させ、説明シーンは再利用するのが推奨パターン。

```
# 節約版 Long の背景割り当て例
背景: 白パンと黒パンの対比（新規生成）
...
背景: 前と同じ   ← 同じ画像を継続、生成なし
...
背景: 製粉小麦の古い工程（新規生成）
```

YMM4 側のズーム・パン・トリミング効果と組み合わせることで、視覚的な変化を維持しながら API 呼び出しを削減できる。

### チャプターマーカー自動生成

Gemini AIがロング台本からYouTube概要欄用チャプターマーカーを生成。

---

## 出力ファイル構成

```
output/{テーマ名}/
├── script.txt              # 台本
├── {テーマ名}.ymmp         # YMM4プロジェクト
├── thumbnails/
│   ├── thumbnail.png                       # サムネイル（UploadはこのA案を使用）
│   ├── {テーマ名}_thumbnail_A.png          # Long: A案
│   ├── {テーマ名}_thumbnail_B.png          # Long: B案
│   └── {テーマ名}_thumbnail_C.png          # Long: C案
├── _meta/
│   ├── metadata.txt                        # タイトル・説明文・タグ
│   ├── opening_review.json                 # 冒頭レビュー結果
│   ├── opening_rewrite_suggestion.txt      # Ollamaリライト内容（発生時のみ）
│   ├── duration_review.json                # 尺レビュー結果
│   ├── final_review.json                   # ChatGPT生成前レビュー結果
│   ├── upload_record.json                  # アップロード記録（スコア含む）
│   ├── thumbnail_ab_test.json              # Long: A/Bテスト管理
│   └── title_ab_test.json                  # Long: タイトルA/B管理
├── audio/
│   └── *.wav
└── backgrounds/
    └── bg_*.png
```

アップロード済みの履歴は `output/000_uploaded/` に移動します。アップロード記録は各動画フォルダの `_meta/upload_record.json` に保存します。予約・公開状態の正は YouTube Data API 側で、スケジュール画面や詰め直しはYouTubeの `publishAt` / `privacyStatus` を参照します。生成時に既存フォルダを退避した `output/000_backups/` の同一テーマバックアップは最新1世代だけ残し、アップロード成功後に削除します。

---

## レイヤー構成

| レイヤー | 用途 |
|---:|---|
| 0 | 背景画像 |
| 1 | トランジション |
| 2 | 固定 BGM |
| 3-4 | 立ち絵 |
| 6 | セリフ字幕 / 音声 |

---

## 立ち絵テンプレート

四国めたんの既定ポーズは、`core/character_templates.json` で両手とも普通手に設定しています。YMM4のPSDレイヤーIDでは、右手が `n16`、左手が `n24` です。目レイヤーは感情・アクション適用時も基本レイヤーが残るよう `core/ymmp_editor.py` で保護しています。

台本の感情指定に応じて、立ち絵へ表情レイヤーと軽いアクションを自動付与します。

```text
ずんだもん(あまあま): うれしいのだ！
ずんだもん(ツンツン): それは違うのだ！
ずんだもん(ささやき): ここだけの話なのだ。
四国めたん(あまあま): いい感じね。
四国めたん(ツンツン): ちょっと待ちなさい。
四国めたん(ささやき): ここだけの話よ。
```

表情と動きの対応は `core/ymmp_editor.py` の `EXPRESSION_LAYER_PRESETS` / `ACTION_PRESETS` で調整できます。

---

## 操作手順

### 初回セットアップ時のプロンプト設定

初回セットアップでは、必ずプロンプト設定を確認します。

初回クローン直後は、Git管理されている食べ物用プロンプト設定でそのまま動きます。別ジャンルで使う場合は、Git管理ファイルを直接編集せず、必ず `core/prompt_parts/local/` に同名の差し替えファイルを置きます。`local/` はGit管理外なので、他人の設定を上書きしません。

食べ物用設定を復元する場合:

```powershell
New-Item -ItemType Directory -Force -Path core\prompt_parts\local
Copy-Item -Path samples\prompt_parts\food\* -Destination core\prompt_parts\local\ -Force
```

### 生成

1. `python gui.py` で起動
2. 必要に応じて `📊 アナリティクス` で実績データを取得
3. `Shortsタイトル案` でタイトル案作成プロンプトをコピーし、候補を作成
4. `AI台本作成` で食べ物雑学特化の台本作成プロンプトをコピー
5. 作成した台本を台本欄に貼り付け
6. 必要に応じて画風を選ぶ
7. `🎬 生成` を押す

生成中に止めたい場合は `作業中止` を押します。押した時点でGUIは中止扱いになり、後続処理へ進みません。外部API呼び出し（画像生成・VOICEVOX通信など）は裏で待つことがありますが、戻ってきた結果は成功扱いにしません。

主要ボタンにカーソルを合わせると、機能概要のツールチップが表示されます。

### Shortsタイトル案 / Longタイトル案

`Shortsタイトル案` は、既存タイトルと直近の YouTube Analytics 実績データを使って、Shorts寄りの食べ物雑学向けタイトル案プロンプトをコピーします。`Longタイトル案` は、Long候補だけを出す条件を付けたプロンプトをコピーします。

- 直近の `output/000_analytics/analytics_score_*.tsv` がある場合、最大80件をプロンプトへ自動差し込み
- 実績データがない場合は、実績根拠のない案を `新規開拓枠` として扱う指示を追加
- 20案の表は軽量化（12列）。詳細（選定理由・台本化理由・想定フック・冒頭1秒・注意点・事実確認ポイント）はTOP5表に集約
- タイトル分類は A〜H。H は「名前・発祥の勘違い」（天津飯・ナポリタン・シュークリーム等）
- 自分ごと化タイトル（勘違い破壊型・損回避型・日常の理由型・名前の罠型など）を20案中5〜7案混ぜる
- TOP5は、タイトル単体ではなく実績データを加味して選定。事実確認ポイント欄を必ず記入
- 実績根拠には、可能な限り `views`、`average_percentage_viewed`、`average_view_duration`、`subscribers_net`、`likes`、`comments` の数値を入れる
- 横展開では「毒だと思われていた」「危険だった」「薬だった」系、袋・容器・穴・形・名前の理由、寿司/魚の価値逆転・名前の罠を優先
- viewsだけで判断せず、平均視聴率・平均視聴時間・高評価率・登録者増を重視。高再生だけの発祥説明型は優先度を下げる
- タイトル本文へ `雑学 ショート` / `食べ物 雑学` / `ゆっくり解説 食べ物` を不自然に入れない。SEO語はタグ・説明欄で補完する
- AIO/SEO補完はタイトルではなく、説明文冒頭の自然文要約、タグ、ハッシュタグ、固定コメントで行う
- 説明文冒頭1〜2行には動画の答えが分かる要約を入れ、固定コメントは要約1文 + 答えやすい質問1文にする
- vidIQ方針として当面はShorts集中。Longは主力にせず、Shortsで実績が出たネタの深掘り候補を優先する
- Shorts案は冒頭1〜3行または5秒以内にタイトルの核心を回収できるものを優先する
- Shorts案は15〜30秒地点に2つ目の驚き、逆転、具体例を入れられる構造を加点する
- コメントしやすい質問（どっち派 / 他にも知ってる / これ知ってた）へ自然につながる案を加点する
- 3選・クイズ形式は実験枠として許可するが、通常の1ネタ深掘りを主力にする
- `analysis_status=data_wait` の動画は優先度A止まり（views 3000以上・likes 30以上・comments 3以上のみ暫定S可）。実績根拠には `暫定` と明記する
- 改善再挑戦枠: views 1000以上かつ平均視聴率30〜49%（条件A）、またはviews 500以上かつlike_rate 1.5%以上（条件B）の既存食材は最大2案まで再挑戦可
- 新規開拓枠は採点7点未満を出力しない
- タイトルは30文字超の場合「意外な」「知られざる」「本当の」「ヤバすぎた」等を優先削除
- 既存食材は原則出さず、例外でも最大2案まで。TOP5には原則入れない
- 同じ横展開元からの案は20案中最大4案、TOP5中最大2案まで
- 型の内訳を20案表の直後に集計出力（自分ごと化/価値逆転/新規開拓/既存食材/改善再挑戦）

`ctr` / `impressions` が 0 または空欄の場合は評価に使わず、views・平均視聴時間・平均視聴率・登録者増減を優先します。

台本生成プロンプトには「スワイプ率対策：ネタ入口パワー判定」を入れています。台本化前に、タイトル・サムネ・冒頭1秒だけで見たくなるかを判定し、弱い場合は名前の罠、昔と今の真逆、食べ物の正体ズレ、袋・容器・包装などの具体物へ切り口を変更します。

プロンプト文章は、固定部分と差し込み部分を分けて扱います。

- 固定部分: チャンネル方針、タイトル・サムネルール、既知ネタ除外、採点、Shorts / Long判定、出力形式、最終チェック
- 差し込み部分: 既存タイトル一覧、既存食材リスト、YouTube Analytics実績データ、実績サマリー、今回の生成条件

コード上では `core/script_prompts.py` の `build_title_prompt()` が固定ルールに差し込みデータを合成します。ネタ固有の差し替え部分は `core/prompt_parts/` に分離しています。

- `title_dynamic_context_food.md`: 実績データ差し込み欄
- `title_duplicate_context_food.md`: 既存タイトル・既存食材・表記ゆれの重複チェック
- `title_used_foods_food.txt`: 既に扱った食材リスト
- `script_generation_prompt.txt`: 台本生成プロンプト全体の個人用差し替え

別ジャンルへ差し替える場合は、上記ファイルを別名で追加し、`build_title_prompt()` が読むファイル名を切り替えます。実績データ未取得時のTSV見出しは `TITLE_ANALYTICS_TSV_HEADER` で管理します。

個人用のネタ設定は `core/prompt_parts/local/` に置きます。このフォルダはGit管理外です。読み込み時は `local/` 側の同名ファイルを優先し、なければGit管理されている `core/prompt_parts/` 側のサンプルを使います。

初回クローン直後は `core/prompt_parts/` 側の食べ物用設定でそのまま動きます。別ジャンル担当者はGit管理ファイルを直接編集せず、自分の環境の `core/prompt_parts/local/` に差し替えファイルを置きます。

AI編集者向けルール:

- ネタ固有のプロンプト、既存食材リスト、別ジャンル用設定を編集する場合は、Git管理されている `core/prompt_parts/*.md` / `*.txt` を直接編集しない。
- 必ず `core/prompt_parts/local/` の同名ファイルを編集する。
- `local/` に同名ファイルがない場合は、`core/prompt_parts/` からコピーして作成してから編集する。
- 例: `core/prompt_parts/title_used_foods_food.txt` を変えたい場合は、`core/prompt_parts/local/title_used_foods_food.txt` を編集する。
- 共有サンプルを更新したい場合だけ、明示的に指示されたうえで `samples/prompt_parts/` または `core/prompt_parts/` を編集する。

例:

- `core/prompt_parts/local/title_used_foods_food.txt`
- `core/prompt_parts/local/title_dynamic_context_food.md`
- `core/prompt_parts/local/title_duplicate_context_food.md`
- `core/prompt_parts/local/script_generation_prompt.txt`

別ジャンル担当者は自分の環境の `local/` に差し替え用ファイルを置けば、Git pull / push で他人のネタ設定を上書きしません。共有用の見本台本は `samples/scripts/` に置きます。

食べ物用の復元サンプルは `samples/prompt_parts/food/` に置きます。`core/prompt_parts/local/` を消してしまった場合は、以下をコピーすれば食べ物用設定を戻せます。

```powershell
Copy-Item -Path samples\prompt_parts\food\* -Destination core\prompt_parts\local\ -Force
```

タイトル・サムネの基本方針:

- タイトルは理由・経緯を伝える
- サムネは一番強い事実を短く刺す
- サムネの衝撃ワードは冒頭5秒以内に回収する
- 抽象表現だけのタイトル・サムネは禁止

### 複数台本の一括生成

次のどちらかで複数動画として扱われます。

- `---` で区切る
- `━━ 動画1：ショート版 ━━` のような見出しを付ける
- `動画形式:` が複数回出てくる

### 履歴から複数生成

`履歴から複数生成` を押すと、`output/` 配下の履歴を複数選択できます。`script.txt` がない履歴は再生成対象にできません。

### 画像確認

`画像確認` を押すと、履歴を選んで以下の画像を確認・再生成できます。

- `thumbnails/thumbnail.png`
- Long動画の `thumbnail A` / `thumbnail B` / `thumbnail C`
- `backgrounds/bg_*.png`

確認画面で再生成したい画像だけ選ぶと、同じファイル名で上書きします。A案を個別再生成した場合は `thumbnail.png` もA案に同期します。

### 動画出力

動画出力は ffmpeg/native MP4 を主経路にします。YMM4 GUI自動操作によるMP4出力は廃止済みで、`.ymmp` は確認・再編集用のプロジェクトとして生成します。

### YouTubeアップロード

`YouTubeアップ` は履歴選択式です。複数の履歴を選択できます。アップロード選択画面には、アップロード可能な `.mp4` がある履歴だけを表示します。各履歴フォルダから最新の `.mp4` を探し、`_meta/metadata.txt` のタイトル・説明文・タグを使ってアップロードします。アップロード成功後は、その履歴フォルダを `output/000_uploaded/` に移動し、各動画フォルダの `_meta/upload_record.json` へ記録します。予約枠の空き判断はローカル台帳ではなくYouTube側の予約状態を参照します。

YouTubeタグは `core/youtube_metadata.py` で一元管理します。AIO/SEO補完として共通タグ（`食べ物雑学`、`食べ物 雑学`、`食べ物の歴史`、`ゆっくり解説`、`ゆっくり解説 食べ物`、`ずんだもん`、`ずんだもん解説`、`四国めたん`、`VOICEVOX`、`雑学ショート` など）を入れ、`食べ物 豆知識` / `食べ物豆知識` やアニメ・ゲーム・都市伝説系タグは除外します。寿司、コンビニ、お菓子、マック、トマト、コーラ、ドリア/洋食などはタイトルや `script.txt` から題材別タグを追加し、タグ欄は500文字以内に調整します。アップロード時に実際に使ったタグを `_meta/youtube_metadata.json` へ保存します。

Long動画のアップロード成功後は、`LONG_UPLOAD_PLAYLIST_NAME` の名前と完全一致する自チャンネルの再生リストへ動画を自動追加します。未設定時の既定値は `ロング動画` です。空にすると無効です。既に同じ動画が入っている場合は重複追加せず、結果を `_meta/upload_record.json` の `playlist_*` フィールドに保存します。Shortsには適用しません。再生リストが見つからない場合、アップロード自体は成功扱いのまま警告ログを出します。

`💬 固定コメント` は、`output/000_uploaded/` 配下のアップロード済み履歴から、固定コメントと `video_id` がある動画を選んでコメント投稿します。投稿成功後は該当動画の `_meta/upload_record.json` に `fixed_comment_thread_id` を保存し、二重投稿を避けます。対象一覧は「未投稿だけ」「公開済みだけ」をデフォルトにし、非公開・存在しない動画・子ども向け設定の動画は投稿前にスキップします。投稿成功時は確認用の一覧画面を表示し、通常動画URLを開けます。ピン留め後は手動で「ピン留め済み」として記録できます。APIで投稿はできますが、ピン留めはYouTube Studio側で確認してください。

台本メタ情報には任意で `生成区分` / `元動画` / `目的` を書けます。`生成区分` は `新規` / `横展開` / `品質改善版` / `再挑戦` を想定します。アップロード時に `_meta/upload_record.json` へ保存し、Analytics一覧で横展開・品質改善版・再挑戦の成果を追えるようにします。

Analytics画面には `高評価率` に加えて `生成区分` / `元動画` / `目的` を表示します。`AI分析用にコピー` と `Shortsタイトル案` / `Longタイトル案` には、対象期間・取得日時、再生数上位・平均視聴率上位・高評価率上位・data_wait注目動画をまとめた実績サマリーを付けます。`AI分析用にコピー` では `analysis_status=data_wait` の動画にも暫定評価コメントを入れるよう指示します。`Longタイトル案` はLong候補だけを出すプロンプトをコピーします。

Analytics一覧は各列のヘッダークリックで昇順/降順ソートできます。数値列は数値として、公開日時は日時として、評価列は `S > A > B > C > D > 未計測 > 対象外` の順で並び替えます。

Analytics APIは期間内に再生のある動画しか返さないため、YouTube Data API でチャンネルのアップロード済み全動画を取得してマージします。Analytics APIにまだ出ていない動画は、Data APIの `statistics` から現在の再生数・いいね数・コメント数を補完しつつ、平均視聴率などがないため `data_wait` としてスコア判定は保留します。200件を超える場合は `startIndex` によるページネーションで全件取得します。

#### 動画スコア判定ルール (`core/analytics_score.py`)

動画種別は秒数で分類します（APIの `video_type` フィールドより優先）。

| 種別 | 秒数 |
|---|---|
| Shorts | 〜60秒 |
| ShortLong | 61〜120秒 |
| Long | 121秒以上 |

各動画には `publish_status` と `analysis_status` が付与されます。

| publish_status | 意味 |
|---|---|
| published | 公開済み |
| scheduled | 公開予約中 |
| private | 非公開 |
| unlisted | 限定公開 |

| analysis_status | score | action | 重複除外対象 |
|---|---|---|---|
| analyzable | S〜D | 通常判定 | ✅ |
| data_wait | 未計測 | データ待ち | ✅ |
| scheduled | 未計測 | 予約中 | ✅ |
| excluded | 対象外 | 対象外 | ❌ |

- 公開予約中・データ待ちは **分析（横展開判定）には使わない** が、タイトル案生成の重複除外には使う
- `build_performance_summary` は `analysis_status == "analyzable"` の動画のみ対象
- `published_at` が 2026-05-16 以前の動画は `audio_cutoff_risk = true` として、音声末尾切れの可能性がある動画として扱う

スコアは `S / A / B / C / D / 未計測 / 対象外` の7段階です。

- **Shorts**: 平均視聴率・平均視聴時間でS〜D判定
- **ShortLong**: Shortsより緩いしきい値でS〜D判定（Long扱いを避ける）
- **Long**: CTR + 平均視聴率でS〜D判定

補正ルール（ベーススコア算出後に適用）：

| 条件 | 効果 |
|---|---|
| Shorts `avg_percent < 45` / ShortLong `avg_percent < 50` | `横展開` に昇格させず `テーマ有望・構成改善` にする |
| Long `ctr < 8` または `avg_percent < 40` | 登録者増だけでは `横展開` にしない |
| `subscribers_net >= 2` かつスコアが B 未満 | スコアを B に引き上げ・action `登録者増・改善候補` |
| `subscribers_net >= 2` かつ最低視聴率ライン以上 | Shorts / ShortLong は action `横展開` |
| `subscribers_net >= 2` かつ Long の横展開条件未達 | action `登録者増・構成改善` |
| `subscribers_net >= 1` かつ弱いスコア | action に `登録導線あり` を補足 |
| `like_rate >= 1.5%` かつ最低視聴率ライン未達 | action `テーマ有望・構成改善` |
| `like_rate >= 1.5%` かつ `score in (C, D)` | action `テーマ有望・冒頭/構成改善` |
| `comments >= 1` かつ弱いスコア | action に `反応あり` を補足 |
| `views < 500` かつ公開後24時間未満 | `is_provisional = true`。横展開系actionには `(判定保留)` を付ける |
| `audio_cutoff_risk = true` かつ公開済み・分析可能な Shorts / ShortLong で `views >= 1000`、`average_percentage_viewed >= 55`、`like_rate >= 1.0`、`comments >= 1`、`subscribers_net >= 1` のいずれか | score は変えず、既存 action に `音切れ改善候補` を補足 |

views 上位20% ルール（`score_items` でまとめて適用）：

- analyzable 動画の views 80パーセンタイル以上 かつ `avg_percent >= 65` → action `横展開・微改善`
- ただし `is_provisional = true` の動画は昇格しない
- Shorts / ShortLong は最低視聴率ライン未満なら昇格しない
- ただし action が `横展開` の場合は維持

TSVには `publish_status` / `analysis_status` / `is_provisional` / `render_engine` 列を含むため、AIへのプロンプト差し込み時に予約中テーマの重複や判定保留を考慮できます。`render_engine` は `_meta/render_info.json` から取得し、アップロード記録に保存されます。
TSVには `audio_cutoff_risk` 列も含み、2026-05-16以前の動画を品質改善版候補として再評価できるようにします。

YouTube Studio 側で予約動画を手動公開した場合:

`📅 スケジュール` を開くと自動的に YouTube API でステータスを確認し、差異があれば確認ダイアログを表示します。

- **手動公開済み検出**: `privacyStatus == "public"` になっていた動画を一覧表示し、確認後に予約スロットから削除・`output/000_data/uploaded_titles.txt` に追記。
- **時刻ズレ修正**: ローカルと YouTube の `publishAt` が 1 分以上ズレている場合、ローカルスケジュールと `upload_record.json` を YouTube 側の時刻に更新。
- 差異がない場合はログに「差異なし」とだけ表示してダイアログを維持。

手動で特定の動画だけを処理したい場合は、行を選択して `手動公開済みにする` ボタンを使います。

予約投稿済み動画の公開予定を変更する場合:

1. `📅 スケジュール` を開く
2. 予定状態の動画を1件選択
3. `公開予定を変更` を押す
4. 日付と時間をプルダウンから選択

This operation updates YouTube `publishAt`. The target video must have a YouTube `video_id`. Allowed times: Shorts 7:00 / 12:00 / 19:00, Long weekday 21:00 and weekend 12:00 / 21:00. If the destination slot already has another video of the same type, the two publish times are swapped on YouTube.

予約スロットを前詰めしたい場合:

1. `📅 スケジュール` を開く
2. `スロット詰め直し` を押す

Future scheduled slots can be packed forward from the earliest available slot. `rebalance_slots()` uses YouTube `publishAt` / `video_id` data, then updates YouTube publish times. Shorts and Long may share the same `publishAt`, but duplicate `publishAt` values within the same video type are treated as rebalance targets. YouTube updates require `video_id`.

Native Shorts rendering places zundamon/metan smaller and slightly higher than the old bottom-aligned layout to reduce overlap with captions. Shorts dialogue captions are center-aligned, use a 1.4x font scale by default, and prioritize readability: white text, speaker-colored inner outline (dark green for zundamon / dark purple-pink for metan), black outer outline, and an optional semi-transparent black band behind captions (`NATIVE_SUBTITLE_BOX_SHORTS`, `NATIVE_SUBTITLE_BOX_OPACITY_SHORTS`). Captions are nudged slightly downward with `NATIVE_SUBTITLE_Y_OFFSET_SHORTS`. These can be adjusted with `NATIVE_CHARACTER_HEIGHT_SHORTS`, `NATIVE_CHARACTER_SIDE_MARGIN_SHORTS`, `NATIVE_CHARACTER_BOTTOM_MARGIN_SHORTS`, `NATIVE_SUBTITLE_FONT_SCALE`, `NATIVE_SUBTITLE_ALIGNMENT_SHORTS`, and `NATIVE_SUBTITLE_Y_OFFSET_SHORTS`.

---

## 台本作成ルール

### 最優先ルール
1. 冒頭1秒で衝撃事実を断言
2. 前置き・挨拶禁止
3. Shortsは1セリフ原則11〜15文字。24〜27行、本文280〜330文字を目標にし、260文字未満は禁止。平均11.5文字以上を維持する。10文字以下の短文は最大4行まで、7文字以下は原則禁止。
4. AI説明口調禁止
5. 掛け合い会話

### キャラ設定
- **ずんだもん**: ボクっ娘。語尾「〜なのだ」。情報を短く投げる役。2chまとめのレス読み上げ風に事実を小出しにする。「なお、原因は〇〇」「結果、〇〇扱い」のような型でテンポを作る。
- **四国めたん**: お嬢様口調。「〜ですわ」「〜よ」。単なる驚き役ではなく、視聴者の違和感・疑問・反論を強めに代弁するツッコミ役。「犯人そっちですの？」「昔の判断、雑すぎますわ」「完全に巻き添えですわ」のような型を使う。

### 掛け合い品質ルール

意味のない相槌は禁止。めたんの「えっ？」「すごいですわ」「知らなかったですわ」「なるほどですわ」は単独使用禁止（必ず具体的な疑問・反論・ツッコミを付ける）。

- めたんの役割: 視聴者の疑問を先回りして言う / 雑な説明に強くツッコむ / 一般的な誤解をあえて口にする / 原因が出た瞬間に強く反応する
- めたんの推奨型: 犯人そっちですの？ / 急に雑ですわ / 昔の判断、雑すぎますわ / 急に工業製品ですわ / 見た目でだましてますわ / 完全に巻き添えですわ
- ずんだもんの役割: 1セリフ1事実で短く投げる / 「昔の人「〇〇やん」」「現代人「なんで？」」「なお、原因は〇〇」「結果、〇〇扱い」型で展開する
- レス読み上げ風の濃さ: Shorts=3〜5割（冒頭・原因・オチで積極的に使う）/ Long=1〜2割（自然な会話に寄せる）。全セリフに適用しない
- 禁止: 草・ワロタ・ンゴ・wwwの多用 / 差別語・罵倒語 / 情報が進まない掛け合い

### Shortsループ構成

最後の1〜2セリフが冒頭の衝撃事実に自然につながる。視聴者が無意識にもう一周見たくなる構成。

### vidIQ反映ルール

- 当面はShorts集中。Longは主力にせず、Shortsで実績が出たネタの深掘りを優先する
- Longを増やすより、Shortsの維持率とコメント率を優先する
- Shorts冒頭1〜3行でタイトルの核心を必ず出し、「今日は〜」「今回は〜」などの導入は禁止する
- タイトルで期待させた内容は5秒以内に回収する
- 冒頭の驚きだけで最後まで引っ張らず、15〜30秒地点に2つ目の驚き、逆転、具体例を入れる
- Shorts本編CTAは最後1行を基本とし、登録お願いよりコメントしやすい質問を優先する
- 3選・クイズ形式は実験枠として許可するが、主力は通常の1ネタ深掘りにする
- SEO語（食べ物雑学 / ゆっくり解説 / ずんだもん）はタイトルへ無理に入れず、タグ・説明欄・ハッシュタグで補完する
- 説明文冒頭1〜2行には答えが分かる自然文の要約を入れる
- Shorts冒頭1〜5秒以内に、題材と結論が分かる一文を掛け合いの中で自然に入れる
- 固定コメントは動画内容の要約1文 + コメントしやすい質問1文で構成する

### CTA優先順位

コメント誘導 > 登録誘導 > 他動画誘導  
お願い口調・事務的定型文禁止。オチの流れで自然に誘導。

### 背景・テロップ

- 背景は展開が変わる時に入れる。Shortsは理想3〜5秒ごと、ロングは基本5〜7秒ごとに見た目を変える。同じ背景を10秒以上続けない
- 台本本編はシーンごとに作る。`# Scene 1: Opening hook` のような見出しを入れ、その下に `背景:`、必要なら `テロップ:`、会話をまとめる
- `# Scene ...` 行は管理用で、アプリ側では無視される
- YMM4字幕は常時表示されるため、追加テロップはセリフの丸写しにしない
- 追加テロップは冒頭フック、重要ワード、章・場面転換、オチ・ツッコミだけに絞る
- Shortsの追加テロップは6〜12個、多くても15個以内。0.8〜1.5秒で短く出す
- Longの追加テロップは少なめにし、章タイトル・数字・年代・固有名詞・重要語を中心にする
- 追加テロップは下に置かない。画面中央、画面上部、右上・左上を使う

### NGワード

NGワードは自動でマイルド表現へ変換されるが、タイトルや説明文は必要に応じて人間が確認する。

---

## 外部サービス依存

| サービス | 用途 | 認証 |
|---|---|---|
| VOICEVOX | 音声合成 | ローカル起動 |
| Google Gemini API | 台本生成・台本チェック | `GOOGLE_API_KEY` |
| Nano Banana (Gemini) | 背景・サムネ画像生成 | `GOOGLE_API_KEY` |
| Ollama (qwen3:8b) | 冒頭品質レビュー・リライト | ローカル起動 |
| OpenAI API | ChatGPT生成前レビュー | `OPENAI_API_KEY` |
| YouTube Data API v3 | 動画アップロード | OAuth2 (`client_secrets.json`) |
| YMM4 | 動画組立・レンダリング | ローカルインストール |

### APIキー・OAuth取得

リポジトリ直下に `.env` を作り、必要なキーを設定します。

```env
GOOGLE_API_KEY=...
OPENAI_API_KEY=...
```

`GOOGLE_API_KEY`:
- 取得先: https://aistudio.google.com/apikey
- 用途: Gemini台本生成、Nano Banana系の背景・サムネ画像生成

`OPENAI_API_KEY`:
- 取得先: https://platform.openai.com/api-keys
- 用途: ChatGPT生成前レビュー
- `OPENAI_FINAL_REVIEW_ENABLED=0` にするとChatGPT生成前レビューを無効化できます。

YouTube OAuth:
- Google Cloud Console でプロジェクトを作成または選択します。
- APIライブラリで `YouTube Data API v3` と `YouTube Analytics API` を有効化します。
- 認証情報で OAuthクライアントIDを作成します。
- アプリケーションの種類は「デスクトップアプリ」を選びます。
- JSONをダウンロードし、ファイル名を `client_secrets.json` にしてリポジトリ直下へ置きます。
- 初回の `YouTubeアップ` 実行時に `token.json`、`📊 アナリティクス` 実行時に `token_analytics.json` が自動作成されます。
- スコープ変更や認証エラーが出た場合は、該当する `token*.json` を削除して再認証します。

取得先:
- Google Cloud APIライブラリ: https://console.cloud.google.com/apis/library
- Google Cloud 認証情報: https://console.cloud.google.com/apis/credentials

秘密情報:
- `.env`
- `client_secrets.json`
- `token.json`
- `token_analytics.json`

これらはGit管理外です。コミットしないでください。

### 設定ファイルで変えられること

主な設定は [config.py](config.py) と `.env` で変更します。

| 設定 | 場所 | 内容 |
|---|---|---|
| `VOICEVOX_URL` | `config.py` | VOICEVOX API のURL |
| `VOICEVOX_PATH` | `config.py` | VOICEVOX実行ファイルの場所 |
| `VOICE_SPEED_SCALE_SHORTS` | `config.py` | Shorts本編の音声速度 |
| `VOICE_INTRO_SPEED_SCALE_SHORTS` | `config.py` | Shorts冒頭の音声速度 |
| `VOICE_SPEED_SCALE_LONG` | `config.py` | Long本編の音声速度 |
| `VOICE_INTRO_SPEED_SCALE_LONG` | `config.py` | Long冒頭の音声速度 |
| `VOICE_INTRO_FAST_SECONDS` | `config.py` | 冒頭高速化する秒数 |
| `VOICE_POST_PHONEME_LENGTH` | `config.py` | VOICEVOX API に渡す `postPhonemeLength` |
| `OPENING_REVIEW_USE_LLM` | `.env` | Ollama冒頭レビューを使うか |
| `OLLAMA_REVIEW_MODEL` | `.env` | 冒頭レビュー用Ollamaモデル |
| `OPENING_REVIEW_AUTO_REWRITE` | `.env` | 冒頭リライトを自動実行するか |
| `OLLAMA_REWRITE_MODEL` | `.env` | 冒頭リライト用Ollamaモデル |
| `OLLAMA_REWRITE_FALLBACK_MODEL` | `.env` | 冒頭リライトのフォールバックモデル |
| `OPENING_SCORE_ABORT_THRESHOLD` | `.env` | 冒頭スコアのpass / warning表示目安 |
| `OPENING_SCORE_HARD_ABORT_THRESHOLD` | `.env` | 重大エラー扱いにするスコア |
| `OPENAI_FINAL_REVIEW_ENABLED` | `.env` | ChatGPT生成前レビューを使うか |
| `OPENAI_FINAL_REVIEW_MODEL` | `.env` | ChatGPT生成前レビューのモデル |
| `SHORT_FULL_SCRIPT_REVIEW` | `.env` | Shortsの全文レビューを行うか |
| `LONG_FULL_SCRIPT_REVIEW` | `.env` | Longの全文レビューを行うか |
| `AUTO_FULL_REWRITE_ENABLED` | `.env` | 全文自動リライトを有効化するか |
| `GEMINI_MODEL` | `.env` / `config.py` | 台本生成で使うGeminiモデル |
| `NANOBANANA_PRO_MODEL` | `.env` / `config.py` | 高品質画像生成モデル |
| `NANOBANANA_FLASH_MODEL` | `.env` / `config.py` | 速い画像生成モデル |
| `CHARACTERS` | `config.py` | VOICEVOX話者ID・スタイルID |
| `CHARACTER_PNGS` | `config.py` | YMM4キャラ立ち絵 |
| `THUMBNAIL_CHARACTER_PNGS` | `config.py` | サムネ生成用参照画像 |
| `BGM_PATH` | `config.py` | 固定BGMファイル |
| `BGM_VOLUME` | `config.py` | BGM音量 |
| `MAX_BACKGROUNDS_SHORTS` | `config.py` | Shortsの最大背景生成枚数 |
| `MAX_BACKGROUNDS_LONG` | `config.py` | Longの最大背景生成枚数 |
| `LONG_UPLOAD_PLAYLIST_NAME` | `.env` | Longアップロード後に自動追加する再生リスト名。未設定時は `ロング動画`。完全一致で検索 |

`.env` の例:

```env
OPENING_REVIEW_USE_LLM=1
OLLAMA_REVIEW_MODEL=qwen3:8b
OPENING_SCORE_ABORT_THRESHOLD=80
OPENAI_FINAL_REVIEW_ENABLED=1
OPENAI_FINAL_REVIEW_MODEL=gpt-5.2
GEMINI_MODEL=gemini-3.1-pro-preview
NANOBANANA_PRO_MODEL=gemini-3-pro-image-preview
NANOBANANA_FLASH_MODEL=gemini-3.1-flash-image-preview
LONG_FULL_SCRIPT_REVIEW=0
LONG_UPLOAD_PLAYLIST_NAME=ロング動画
```
## CTA / 導線制御

- Shortsは本編内の他動画誘導より、完走率・平均視聴率・ループ視聴を優先する。
- Shortsの `次回は` / `次の動画` / `他の動画も見て` / `チャンネル登録お願いします` / `高評価お願いします` は生成前チェックで警告する。
- `core/cta_policy.py` が一括生成時の `ネタ募集CTA: 許可 / 禁止` を判定する。Shortsかつ生成区分が `新規` / `横展開`、同時生成5本以上の場合のみ最大1本許可する。
- ネタ募集CTAを許可した台本で固定コメントが未指定なら、ネタ募集用固定コメントを自動差し込みする。
- Longでは関連動画誘導・vidIQタイトル調整・説明欄YouTubeチャプター追加を許可する。アップロード時に `チャプター:` 行または既定章立てから `【目次】` を説明欄末尾へ追加する。
- CTA方針は `_meta/cta_policy.json`、アップロード時のYouTubeメタ方針は `_meta/youtube_metadata.json` に保存する。
