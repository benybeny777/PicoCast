# ずんかみ自動生成システム 仕様書

チャンネル: [ずんだもんとめたんの食べ物雑学堂](https://www.youtube.com/@zunkami)  
最終更新: 2026-05-17

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
│   ├── ymm4_renderer.py    # YMM4レンダリング制御
│   ├── opening_quality.py  # 冒頭品質レビュー
│   ├── script_prompts.py   # 台本生成プロンプト (Python)
│   ├── script_generation_prompt.txt  # 台本生成プロンプト (テキスト)
│   ├── upload_scheduler.py # アップロードスケジュール管理
│   ├── youtube_uploader.py # YouTube APIアップロード
│   └── ng_words.py         # NGワード置換
└── output/                 # 生成物出力先
    ├── upload_schedule_shorts.json
    └── upload_schedule_long.json
```

---

## 動画フォーマット

### Shorts
- 尺: **45〜52秒（理想）/ 35〜55秒（許容）**
- セリフ数: **17〜20行（21行以上禁止）**
- 尺計算式: `総文字数 × 0.11秒 + 行数 × 1.2秒 = 推定尺`
- 背景枚数: 6〜9枚
- 再生速度: イントロ2.0x（最初5秒）/ 本編1.65x
- アップロードスロット: 毎日 0:00 / 7:00 / 12:00 / 19:00 (JST)

### Long
- 尺: **5〜10分（理想5〜8分）**
- セリフ数: 150〜250行
- 背景枚数: 5〜7秒に1枚（同一背景10秒以上禁止）
- 再生速度: イントロ1.6x / 本編1.35x
- アップロードスロット: **土日のみ** 12:00 / 19:00 (JST)

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
   ├── Ollamaレビュー（スコア<75の場合）
   └── 必要に応じてOllamaリライト → 再パース
6. スコアが閾値未満なら処理中止 (デフォルト80点)
7. VOICEVOX音声生成（セリフ1行ずつ）
8. 背景画像生成（Nano Banana）
   └── 再利用チェック: 台本変更で枚数が変わる場合は全再生成
9. サムネイル生成（Nano Banana）
10. YMM4プロジェクト組立 (.ymmp)
11. BGM追加
12. YMM4プロジェクト保存
13. 尺推定 + 尺レビュー
14. ChatGPT最終レビュー（評価のみ、修正なし）
15. 完了レポート
```

### 尺推定 (gui.py: `_estimate_shorts_duration`)

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
| Ollamaレビュー | `qwen3:8b` でLLMスコアリング | ローカルスコア < 75 |
| Ollamaリライト | 冒頭セリフを自動修正 | `should_auto_rewrite_opening` = True |

### `should_auto_rewrite_opening` の条件（いずれか）

- `must_fix` に項目がある
- `hook < 75` / `loop < 70` / `cta < 70`
- 総合スコア < 80

### 処理中止条件

リライト後のスコアが `OPENING_SCORE_ABORT_THRESHOLD`（デフォルト80）未満 → パイプライン中止

### ChatGPT最終レビュー

- モデル: `OPENAI_FINAL_REVIEW_MODEL`（デフォルト `gpt-5.4-mini`）
- 入力: タイトル / サムネ文字 / 固定コメント / 台本 / 各レビュー結果 / 推定尺
- 出力: `final_score` / `publish_ok` / `risk` / `must_fix` / `nice_to_fix`
- **自動修正なし** — ログ表示と `final_review.json` 保存のみ

### 保存ファイル

| ファイル | 内容 |
|---|---|
| `opening_review.json` | ローカル・Ollamaレビュー結果、final_score、final_status |
| `opening_rewrite_suggestion.txt` | Ollamaリライト内容（リライトが発生した場合） |
| `duration_review.json` | 尺レビュー結果（seconds / status / ideal） |
| `final_review.json` | ChatGPT最終レビュー結果 |

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
| Shorts | 0:00 / 7:00 / 12:00 / 19:00 | 毎日 |
| Long | 12:00 / 19:00 | 土日のみ |

- スケジュールは `output/upload_schedule_shorts.json` / `upload_schedule_long.json` に永続化
- スロット割当範囲: 最大90日先まで探索
- アップロード実行後: `upload_record.json` にスコア情報を保存

---

## GUI (`gui.py`)

### 主要タブ・機能

| 機能 | 説明 |
|---|---|
| 台本生成 | Gemini AIによる台本生成（テーマ入力 or 台本直接入力） |
| 履歴から生成 | 過去生成済みテーマを選択して再生成 |
| アップロード | 複数動画の一括スケジュールアップロード |
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
| 35〜44秒 | 黄 (warning) |
| 45〜52秒 | 緑 (success) ← 理想 |
| 52〜55秒 | 黄 (warning) |
| 55〜58秒 | 橙 (warning) |
| > 58秒 | 赤 (error) |

### 事前チェック (`_pre_generate_check`)

エラー（中止）:
- タイトル未設定

警告（ログのみ）:
- サムネ文字が15文字超
- 背景枚数が少ない
- VOICEVOX手書きクレジット
- 最初のセリフが8文字未満

### アップロード確認ダイアログ

- 列: 番号 / タイトル / スケジュール / スコア（冒頭 / 尺 / 最終）
- 幅: 860px

---

## VOICEVOX音声生成 (`core/voicevox.py`)

- API: `/audio_query` → `/synthesis` を1行ずつ個別呼び出し
- 末尾無音: 0.5秒をWAVに直接追加（`postPhonemeLength` APIは使用しない）
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

---

## 台本フォーマット

### Shortsフォーマット例

```
動画形式: Shorts
動画タイトル: チョコは500年間ずっと飲み物だった
サムネ文字: 飲み物
説明文: #ずんだもん #ゆっくり解説 チョコレートの驚きの歴史を解説！
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
| `VOICE_SPEED_SCALE_SHORTS` | 1.65 | Shorts本編再生速度 |
| `VOICE_INTRO_SPEED_SCALE_SHORTS` | 2.0 | Shortsイントロ再生速度 |
| `VOICE_INTRO_FAST_SECONDS` | 5.0 | イントロ高速区間（秒） |
| `VOICE_SPEED_SCALE_LONG` | 1.35 | Long本編再生速度 |
| `VOICE_INTRO_SPEED_SCALE_LONG` | 1.6 | Longイントロ再生速度 |
| `GEMINI_MODEL` | `gemini-3.1-pro-preview` | 台本生成モデル |
| `OLLAMA_REVIEW_MODEL` | `qwen3:8b` | 冒頭レビューモデル |
| `OLLAMA_REWRITE_MODEL` | `qwen3:8b` | 冒頭リライトモデル |
| `OPENAI_FINAL_REVIEW_MODEL` | `gpt-5.4-mini` | 最終レビューモデル |
| `OPENING_SCORE_ABORT_THRESHOLD` | 80 | 中止スコア閾値 |
| `MAX_BACKGROUNDS_SHORTS` | 9 | Shorts最大背景枚数 |
| `MAX_BACKGROUNDS_LONG` | 90 | Long最大背景枚数 |
| `BGM_VOLUME` | 15.0 | BGM音量(%) |

---

## Long動画専用機能

### サムネイルA/Bテスト

3バリアントのサムネイルを生成し `thumbnail_ab_test.json` で管理:
- **Variant A**: 食べ物クローズアップ（クリック重視）
- **Variant B**: 古い歴史・驚き演出
- **Variant C**: 昔と今の比較・ギャップ

アップロード後にYouTube動画IDを `thumbnail_ab_test.json` に記録。

### タイトルA/Bテスト

`title_ab_test.json` でタイトルバリアントを管理（手動切り替え）。

### チャプターマーカー自動生成

Gemini AIがロング台本からYouTube概要欄用チャプターマーカーを生成。

---

## 出力ファイル構成

```
output/{テーマ名}/
├── script.txt              # 台本
├── opening_review.json     # 冒頭レビュー結果
├── duration_review.json    # 尺レビュー結果
├── final_review.json       # ChatGPT最終レビュー
├── upload_record.json      # アップロード記録（スコア含む）
├── thumbnail.png           # サムネイル
├── thumbnail_ab_test.json  # Long: A/Bテスト管理
├── title_ab_test.json      # Long: タイトルA/B管理
├── bg/
│   ├── bg_0001.png         # 背景画像（4桁連番）
│   └── ...
└── {テーマ名}.ymmp         # YMM4プロジェクト
```

---

## 台本作成ルール要約

### 最優先ルール
1. 冒頭1秒で衝撃事実を断言
2. 前置き・挨拶禁止
3. 1セリフ15文字以内
4. AI説明口調禁止
5. 掛け合い会話

### キャラ設定
- **ずんだもん**: ボクっ娘。語尾「〜なのだ」。ナビ役。
- **四国めたん**: お嬢様口調。「〜ですわ」「〜よ」。鋭いツッコミ役。

### Shortsループ構成
最後の1〜2セリフが冒頭の衝撃事実に自然につながる。視聴者が無意識にもう一周見たくなる構成。

### CTA優先順位
コメント誘導 > 登録誘導 > 他動画誘導  
お願い口調・事務的定型文禁止。オチの流れで自然に誘導。

---

## 外部サービス依存

| サービス | 用途 | 認証 |
|---|---|---|
| VOICEVOX | 音声合成 | ローカル起動 |
| Google Gemini API | 台本生成・台本チェック | `GOOGLE_API_KEY` |
| Nano Banana (Gemini) | 背景・サムネ画像生成 | `GOOGLE_API_KEY` |
| Ollama (qwen3:8b) | 冒頭品質レビュー・リライト | ローカル起動 |
| OpenAI API | 最終レビュー | `OPENAI_API_KEY` |
| YouTube Data API v3 | 動画アップロード | OAuth2 (`client_secrets.json`) |
| YMM4 | 動画組立・レンダリング | ローカルインストール |
