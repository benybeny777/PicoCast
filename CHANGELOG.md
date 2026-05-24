# 変更履歴

このファイルには、運用や品質に影響する大きめの変更を残します。

書く目安:
- プロンプト方針を大きく変えた
- YouTube Analytics、アップロード、スケジュールなど運用フローを変えた
- 生成物の品質レビュー、尺チェック、NGワードなど判定基準を変えた
- GUIの主要ボタンや出力形式を変えた

細かい文言修正や見た目だけの軽微な変更は、必要な場合だけ書きます。

---

## 2026-05-25 (4)

### native/ffmpegレンダラー改善（音量・字幕・キャラ・実尺ログ）

- `core/native_renderer.py`: native出力のBGM音量を `NATIVE_BGM_VOLUME_DB=-20dB` で指定するよう変更（従来の `BGM_VOLUME` パーセント指定はYMM4専用に分離）
- `core/native_renderer.py`: native MP4生成後に ffprobe で実尺を取得し `📏 native実尺評価: Xs [理想/やや短い/OKだけど長め/警告/要確認]` をログ表示。`estimated_duration_sec` 引数があれば推定尺との差分も表示
- `core/native_renderer.py`: `_meta/render_info.json` に render_engine / actual_duration_sec / actual_duration_status / loudnorm_enabled / loudnorm_i/tp/lra を保存
- `core/native_renderer.py`: native Shorts のキャラ表示に `NATIVE_SHORTS_CHARACTER_SCALE`(デフォルト 1.05)を適用。Long/YMM4には影響しない
- `core/native_renderer.py`: 字幕フチ幅を `NATIVE_SUBTITLE_OUTER_STROKE_WIDTH`(13) / `NATIVE_SUBTITLE_STROKE_WIDTH`(9) に変更（従来ハードコードの 12/8 より少し太め）、字幕帯高さに `NATIVE_SUBTITLE_PADDING_Y`×2 を加算
- `config.py` / `README.md` / `SPEC.md`: `NATIVE_BGM_VOLUME_DB` / `NATIVE_SHORTS_CHARACTER_SCALE` を追加

### YouTubeタグ共通タグ見直し（vidIQ分析に基づく）

- `core/youtube_metadata.py`: `VIDEO_DEFAULT_TAGS` の先頭を `ずんだもん,ゆっくり解説,VOICEVOX` に固定し、`食べ物 雑学 ショート`/`食べ物雑学`/`食べ物の歴史`/`VOICEVOX解説`/`トリビア` 等を追加。需要の低い `コンビニ 雑学`/`料理 歴史`/`面白い 雑学`/`食べ物` を削除
- `core/youtube_metadata.py`: 題材別タグルールを更新。アイス系・寿司系・飲み物系・お菓子系・調味料系を追加・整理
- `SPEC.md`: YouTubeタグポリシーの最新ルールを反映

## 2026-05-25 (3)

### native/ffmpeg音声にloudnormを追加

- `core/native_renderer.py`: native MP4の最終音声出力に `loudnorm=I=-15:TP=-1.5:LRA=6` を追加。BGM/VOICEミックス後、最終出力直前の音声だけに適用し、映像はコピーする
- `core/native_renderer.py`: native MP4出力後に ffmpeg `ebur128=peak=true` で音量解析し、Integrated loudness / LRA / True peak の要約をログ出力
- `config.py` / `README.md` / `SPEC.md`: `NATIVE_AUDIO_LOUDNORM_ENABLED` / `NATIVE_AUDIO_LOUDNORM_I` / `NATIVE_AUDIO_LOUDNORM_TP` / `NATIVE_AUDIO_LOUDNORM_LRA` を追加

### 外部APIモデル設定を点検・更新

- `config.py` / `README.md` / `SPEC.md`: ChatGPT生成前レビューの既定モデルを公式モデル一覧で確認できる `gpt-5.2` へ更新
- `config.py`: Gemini / Nano Banana のモデルIDを `.env` から上書きできるよう変更し、API側のモデル更新に追随しやすくした
- `core/image_generator.py`: Gemini画像生成リクエストに画像出力モダリティと縦横比設定を明示

### 生成前レビュー失敗時に一括生成を即停止

- `gui.py`: `run_pipeline()` が `❌` / `⏹` を返した場合、一括生成でも次の動画へ進まず即終了するよう変更。ChatGPT生成前レビューの接続失敗などを「要修正」ログだけで継続しない
- `core/opening_quality.py` / `gui.py`: 生成前スコアリング開始時にChatGPT生成前レビューのOpenAI接続を確認し、DNS失敗・認証失敗・API接続失敗時は生成開始前に即停止するよう変更
- `main.py`: 単発生成でもChatGPT生成前レビューの直前にOpenAI接続チェックを行い、失敗時はレビューAPI呼び出しに進まず停止するよう変更

### APIクライアントの明示解放を追加

- `core/youtube_uploader.py` / `core/youtube_analytics.py`: YouTube Data API / Analytics API の googleapiclient resource を処理後に `close()` するよう変更
- `core/ai_generator.py` / `core/image_generator.py`: Google GenAI クライアントに `close()` / context manager を追加
- `main.py` / `gui.py`: 短命の Gemini / Nano Banana 生成器を使用後に明示的に閉じるよう変更

### 作業ガイドと環境説明を更新

- `AGENTS.md` / `CLAUDE.md`: リソース明示解放、メモリ解放、認証情報の記載・コミット禁止を恒久ルールに追加
- `AGENTS.md` / `CLAUDE.md` / `README.md` / `SPEC.md`: YMM4 GUI自動操作を廃止済みとして、ffmpeg/native MP4を主経路、YMM4は確認用 `.ymmp` 生成までの説明に更新

### YouTubeソース化後のテストとドキュメントを整備

- `tests/test_upload_scheduler.py`: `rebalance_slots()` 系テストをYouTube予約一覧のモックに変更し、テスト実行時に実YouTube APIへアクセスしないよう修正
- `SPEC.md` / `README.md`: 中央 `upload_records.json` 前提の古い説明を、YouTube APIを予約・公開状態の正とする現行仕様へ更新

### ローカルスケジュール管理を完全廃止・YouTube をソースオブトゥルースに

**廃止**:
- `output/000_data/upload_records.json`（中央アップロード台帳）を廃止
- `save_upload_records()` / `upsert_upload_record()` を no-op 化
- スケジュールに関わるローカルファイル読み書きをすべて除去

**変更**:
- `core/upload_records.py`: `load_upload_records()` を出力フォルダ配下の `_meta/upload_record.json` をスキャンする実装に置き換え。各レコードに `_local_path` を付加して固定コメント書き戻し先を特定可能に
- `core/upload_scheduler.py`: `schedule_from_youtube()` / `_scheduled_entries_from_youtube()` を追加。`list_schedule()` / `rebalance_slots()` / `rebalance_slots_detailed()` / `count_rebalance_candidates()` を YouTube API ベースに切り替え
- `gui.py` スケジュールダイアログ: `build_rows()` を YouTube `get_channel_upload_video_statuses()` 直接参照に書き換え。ローカル台帳参照を廃止
- `gui.py` リバランスワーカー: ローカルレコード更新処理を全削除。YouTube 更新のみ実行
- `gui.py` 固定コメント候補収集: `_local_path` を使ってスレッドID書き戻し先を特定
- `gui.py` `_write_upload_record_data`: 中央ファイルパス宛の書き込みを no-op 化

**維持**:
- 動画ごとの `_meta/upload_record.json`（スコア・メタデータ）は引き続き書き込み
- Analytics は `load_upload_records()` 経由でフォルダスキャン結果を参照（関数シグネチャ変更なし）

---

## 2026-05-25 (2)

### アップロードスロット割り当てを YouTube 参照に変更

- `core/upload_scheduler.py`: `assign_slots_from_youtube(count, video_type)` を追加。YouTube チャンネルの予約投稿済み動画（private + 未来の publishAt）を取得し、同タイプの使用済みスロットとして扱う。YouTube API が失敗した場合のみローカルレコードにフォールバック
- `gui.py`: アップロード時のスロット割り当てを `assign_slots_from_youtube` に切り替え。ローカルの `upload_records.json` を空き枠判断に使わなくなったため、ローカル状態のズレによる重複スロットが発生しない
- `core/upload_records.py`: `upsert_upload_record` に重複スロット検出ログを追加（同タイプ・同 publish_at が別 video_id にある場合 WARNING）

---

## 2026-05-25

### ChatGPT生成前レビューのnative Shorts基準を修正

- `core/opening_quality.py`: ChatGPT生成前レビュープロンプトに `render_engine` を渡し、native Shortsでは「31行以上のみmust_fix / 24〜27行が理想」に修正。旧YMM4基準「21行以上=must_fix」は完全削除
- `core/opening_quality.py`: native Shorts かつ dialogue_count <= 28 の場合、ChatGPT応答に旧基準由来の「21行以上 must_fix」が返ってきても自動で除去するポストフィルタを追加
- `main.py`: `final_chatgpt_review()` に `render_engine=_render_engine` を渡すよう修正
- `core/opening_quality.py`: 冒頭1行目の食べ物名チェックを改善。タイトルが抽象的でも `FOOD_HINT_WORDS`（コーヒー・コーラ・牛乳等の飲み物含む）が初行に直接あればOKとした。N選型タイトルは代表食材1つあればOKで、全食材名列挙は不要に変更
- `SPEC.md`: 上記基準を反映

### native Shorts字幕のキャラ色フチを強化

- `core/native_renderer.py`: 半透明黒帯と白文字を維持したまま、ずんだもん/めたんのキャラ色内フチを太くし、黒外フチも少し太くして可読性を保ったまま話者色を見やすく調整
- `SPEC.md` / `docs/YMM_FREE_RENDERER.md`: native字幕の可読性方針と、現在のnative出力名・処理フローに合わせてドキュメントを更新

### 背景生成時のリファレンス画像渡しを廃止

- `main.py`: Long動画で1枚目の背景を2枚目以降のスタイル参照として渡していた処理を削除
- `gui.py`: 背景再生成時に別の既存背景をスタイル参照として渡していた処理を削除
- サムネイル生成でのキャラ画像渡しは引き続き有効

---

## 2026-05-23

### vidIQ方針を台本・タイトル案プロンプトへ反映

- `core/prompt_parts/local/script_generation_prompt.txt`: Shorts集中、冒頭1〜3行でタイトル核心回収、15〜30秒地点の二段フック、コメント誘発、3選/クイズ実験枠、SEO語はタイトルへ無理に入れない方針を追加
- `core/prompt_parts/local/title_dynamic_context_food.md` / `core/script_prompts.py`: タイトル案生成でShorts維持率・コメント率を優先し、LongはShorts実績ネタの深掘り候補に限定する方針を追加
- `core/youtube_metadata.py`: AIO/SEO補完用の共通タグを強化し、説明文のSEO補完文を冒頭側に入れるよう変更。ドリア/洋食系の題材別タグを追加
- `core/prompt_parts/local/script_generation_prompt.txt` / `core/script_prompts.py` / `core/ai_generator.py`: 説明文冒頭の自然文要約、固定コメントの要約1文+質問1文、Shorts冒頭1〜5秒で題材と結論を明文化するルールを追加
- `SPEC.md`: 台本作成ルールとタイトル案運用にvidIQ反映ルールを追記

### native Shortsのキャラ配置と字幕位置を調整

- `config.py`: Shortsのずんだもん/めたん立ち絵をやや大きめ・外側配置・下側クロップにし、腰から上が見える構図へ調整
- `core/native_renderer.py`: Shorts字幕を中央寄せにし、字幕フォントサイズを既存比40%拡大。通常字幕は白文字＋話者別の濃色内フチ（ずんだもん=濃緑、めたん=濃紫ピンク）＋黒外フチに変更し、必要時に半透明黒帯を背面へ出せるようにした。字幕を少し下げ、環境変数で `NATIVE_SUBTITLE_FONT_SCALE` / `NATIVE_SUBTITLE_ALIGNMENT_SHORTS` / `NATIVE_SUBTITLE_Y_OFFSET_SHORTS` / `NATIVE_SUBTITLE_BOX_SHORTS` / `NATIVE_SUBTITLE_BOX_OPACITY_SHORTS` / キャラ余白を調整可能に変更

### アップロード公開時刻の同タイプ重複を詰め直しで解消

- `core/upload_scheduler.py`: `rebalance_slots_detailed()` が `video_id` に加えて upload_records のレコード番号を返し、同時刻・同タイトル・video_idなしの重複でも対象レコードを特定できるように変更
- `core/upload_scheduler.py`: スロット詰め直し時、`generation_kind` が入っている動画（横展開・品質改善版・再挑戦など）を同タイプ内で優先して早い枠へ割り当てるように変更
- `gui.py`: スロット詰め直し適用時にレコード番号を使って `output/000_data/upload_records.json` を直接更新。`video_id` がない場合もローカルの予約時刻は詰め直す
- Shorts と Long は従来通り同時刻を許容。同タイプ内（Shorts同士 / Long同士）の同時刻重複を解消する
- `tests/test_upload_scheduler.py`: Shorts / Long の同時刻重複と video_id なし重複のテストを追加

### native MP4生成後に実尺チェックを追加

- `gui.py`: `render_native_test()` 完了後に `duration_review()` で実尺を判定し、`━━ 実尺チェック XX.X秒 / [ラベル] ━━` 形式でログ表示（ideal→緑 / warning→黄 / needs_review→赤）
- 判定結果を `_meta/duration_review.json`（`source: native_mp4`）に保存
- 完了メッセージにも判定ラベルを追記

### 5/16以前の音切れリスク動画をAnalyticsで品質改善版候補化

- `core/analytics_score.py`: 2026-05-16以前の公開動画に `audio_cutoff_risk` を付与し、実績シグナルがある Shorts / ShortLong の action に `音切れ改善候補` を補足
- Analytics TSV / GUI一覧 / タイトル案プロンプトの実績データヘッダーに `audio_cutoff_risk` を追加
- タイトル案プロンプトに、音切れリスク動画をネタ弱いと即断せず「品質改善版」候補として扱う指示を追加
- `tests/test_analytics_score.py`: 音切れリスク境界日、候補付与条件、TSV列のテストを追加

### native MP4の先頭フレームにサムネイル挿入・固定ファイル名で上書き

- `core/native_renderer.py`: Shorts の native MP4 先頭1フレームに `thumbnails/thumbnail.png` を挿入（Long は挿入しない）
- `core/native_renderer.py`: native MP4出力名を `{履歴フォルダ名}_native.mp4` に固定。タイムスタンプなし・再生成時は上書き
- native MP4化前に `_native_test` の古い中間ファイルを削除し、再生成画像を使った出力になるように整理
- `gui.py`: 画像再生成時に対象画像を上書きし、更新時刻も明示的に更新

### アップロードスケジュール画面に公開済み動画の YouTube 公開日時を表示

- `gui.py`: `📅 スケジュール` 画面に公開済み動画（直近90日）を追加表示。日時列は YouTube 側の `published_at`（API同期値）を使用
- 状態フィルタ追加: すべて / 予定 / 公開済
- 公開済み行を緑色で表示。カウント表示に「公開済 N 件 (直近90日・YouTube同期値)」を追加

### 投稿テンプレート終盤のCTA記述を修正

- `core/prompt_parts/local/script_generation_prompt.txt`: 投稿テンプレートの「終盤: 真相 → オチ → 他動画誘導 → 登録誘導」を「真相 → オチ → 冒頭キーワードに戻す」へ修正し、Shortsループ優先ルールと完全に整合

### Shorts CTAルールとレス読み上げ風ルールを整理

- `core/prompt_parts/local/script_generation_prompt.txt`: Shorts理想構成に残っていた「他動画誘導・登録・高評価誘導を2〜3行に凝縮」という古いCTA記述を削除
- Shortsはループ締めまたはコメント誘導を優先し、CTAは1種類だけに統一（Shorts CTA構成節も同様に整合）
- 品質改善版・再挑戦ではネタ募集CTAを原則使わない方針を明記
- レス読み上げ風の濃度をShorts 2〜4割、Long 1〜2割へ調整し、下品なネットスラングは禁止に整理

### 台本プロンプト: 掛け合い品質・強めツッコミルール追加

- `core/prompt_parts/local/script_generation_prompt.txt`: ずんだもんを「2chまとめレス読み上げ風」、四国めたんを「視聴者の違和感・疑問・反論を強めに代弁するツッコミ役」に再定義
- 掛け合い品質ルール新設: めたんの意味のない相槌・驚き専用フレーズを禁止リストに追加
- ずんだもん推奨型（「昔の人「〇〇やん」」「現代人「なんで？」」「なお、原因は〇〇」「結果、〇〇扱い」）を追加
- めたん推奨型（「犯人そっちですの？」「急に雑ですわ」「完全に巻き添えですわ」等）を追加
- BAD/GOOD台本例（トマト・カップ麺）を追加してモデルの学習容易性を高める
- Shorts/Long 濃度分け: Shorts=3〜5割（冒頭・原因・オチで積極的に使う）/ Long=1〜2割（自然な会話に寄せる）を明記
- 禁止事項に「めたんの意味のない相槌禁止 / 情報が進まない掛け合い禁止」を追記
- 自己チェック項目に掛け合い品質5項目を追加

### 画像SD生成モードを追加（GUIチェックボックス）

- `core/image_generator.py`: `sd_size_mode=True` で `SD_SIZE_IMAGE_SCALE`（デフォルト0.5）倍サイズで生成し元サイズに拡大してセット
- `config.py`: `SD_SIZE_IMAGE_SCALE` 環境変数を追加（デフォルト0.5）
- `gui.py`: 「SD生成」チェックボックス追加（デフォルトOFF）。生成・画像確認再生成・サムネイル再生成の全パスに伝播
- `main.py`: `run_pipeline()` / `regenerate_thumbnail_only()` に `sd_size_mode` パラメータを追加

### data_wait動画にもAI分析コメントを出すように変更

- `core/analytics_score.py`: 実績サマリーに data_wait 件数と注目動画を追加
- `core/analytics_score.py`: Analytics保存JSONに `start_date` / `end_date` / `summary` を保存し、実績サマリーに対象期間・取得日時を表示
- `gui.py`: Analyticsの「AI分析用にコピー」に、data_wait動画へ暫定評価コメントを必ず入れる指示を追加
- `gui.py`: Analytics画面の取得結果表示に対象期間を追加
- `core/script_prompts.py`: タイトル案プロンプトで data_wait 動画にも「暫定横展開候補」「要追跡」「判断保留」などの短い評価コメントを書くよう明記

---

## 2026-05-22（続き4）

### Shorts台本文字数ガイドラインをnative速度に合わせて更新

- `core/prompt_parts/local/script_generation_prompt.txt`
  - 尺計算式を旧YMM4式（×0.11＋×1.2）→ native式（÷3.75＋×0.25）に更新
  - 1セリフは原則11〜15文字、平均11.5文字以上を維持するルールに更新
  - Shorts nativeでは24〜27行、本文280〜330文字を目標にし、260文字未満は禁止
  - 10文字以下の短文は最大4行まで、7文字以下は原則禁止
- `SPEC.md`: 台本作成ルール・Shorts セリフ数・尺計算式を同様に更新
- `gui.py` / `main.py`: `_estimate_duration` / `_estimate_script_duration` の `native_render` パラメータを削除し、Shorts=native速度/Long=YMM4速度で分岐

---

## 2026-05-22（続き3）

### アナリティクス・アップロード記録に render_engine を追加

- `core/analytics_score.py`: `to_tsv()` の列に `render_engine` を追加（`genre_group` の直後）
- `gui.py` `_write_upload_record`: `_meta/render_info.json` を読み込み `render_engine` フィールドをアップロード記録に保存
  - アップロード後のアナリティクス画面の TSV にも自動反映

---

## 2026-05-22（続き2）

### Shorts本番レンダリングをffmpeg/nativeへ移行

- **Shorts生成のデフォルトをnativeに変更**
  - `DEFAULT_SHORTS_RENDER_ENGINE = "native"` (config.py / ENV上書き可)
  - `run_pipeline(native_render=None)` がShortsを検出すると自動でnativeに切り替わる
  - 通常の「生成」ボタンがShortsをnativeで出力するようになった（YMMなし専用ボタン不要）
  - YMM4プロジェクト生成は継続（保険・確認・再編集用）
  - `RENDER_WITH_YMM4 = False` でYMM4本番書き出しをデフォルト無効化
- **GenerationReport.native_render_used** を追加し、GUIがnativeレンダリングを自動トリガー
- **出力ファイル名を `video_native.mp4` に変更**（旧: `{folder名}_native_test.mp4`。2026-05-23に `{フォルダ名}_native.mp4` 固定へ再変更）
- **アップロード優先順位を更新**: 履歴フォルダ内の最新 MP4 を選択（固定ファイル名のため常に1本）
- **冒頭速度切り替えをline_countモードに変更**（native Shorts）
  - 旧: フレーム上の5秒経過で切り替え
  - 新: 冒頭3行（`VOICE_INTRO_FAST_LINES=3`）がintro速度、4行目以降がbody速度
- **render_info.json を `_meta/` に保存**（render_engine・voice_speed・ymm4_project_generated）
- **native prompt追加**: script_generation_prompt.txt に「native/ffmpeg Shortsルール」と「展開密度ルール」を追記
- **native生成ログにmax_silenceを追加**
- **config.py に追加した定数**:
  - `NATIVE_SHORTS_INTRO/BODY_VOICE_SPEED_MIN/MAX` (許容範囲)
  - `NATIVE_MIN/DEFAULT/SCENE_CHANGE/MAX_NORMAL/WARNING_SILENCE` (無音設定)
  - `YMM4_SHORTS/LONG_INTRO/BODY_VOICE_SPEED` (明示エイリアス)
  - `VOICE_INTRO_FAST_MODE` / `VOICE_INTRO_FAST_LINES`

---

## 2026-05-22（続き）

### ffmpeg nativeレンダラー: エンジン別安定条件・音声速度分離

- `config.py`: YMM4とnativeで音声速度定数を分離
  - `NATIVE_SHORTS_BODY_VOICE_SPEED=1.25` / `NATIVE_SHORTS_INTRO_VOICE_SPEED=1.40`
  - `NATIVE_LONG_BODY_VOICE_SPEED=1.20` / `NATIVE_LONG_INTRO_VOICE_SPEED=1.40`
  - すべて `.env` で上書き可能（`NATIVE_SHORTS_BODY_VOICE_SPEED` 等）
  - 既存の YMM4 速度定数（`VOICE_SPEED_SCALE_SHORTS` 等）は変更なし
- `config.py`: native Shorts のセリフ数しきい値を追加
  - 理想: 22〜28行 / warning: 29〜30行 / must_fix: 31行以上
- `core/opening_quality.py`: `local_opening_review` に `render_engine` 引数を追加
  - `render_engine="ymm4"`: 21行以上 → must_fix（従来通り）
  - `render_engine="native"`: NATIVE_SHORTS_LINES_* に従う
- `main.py`: `run_pipeline` に `native_render` 引数を追加
  - `_render_engine` を派生し `local_opening_review` へ渡す
  - native では推定尺による停止をスキップし参考ログのみ表示
  - 音声速度は native/YMM4 の定数から分岐して選択
- `core/native_renderer.py`: `render_native_test` に `voice_speed_intro/body` 引数を追加
  - 完了時に語り速度（chars/sec）・台本量・速度判定・台本量判定を含む詳細ログを出力
- `gui.py`: 生成前スコアゲートと render_native_test 呼び出しをエンジン対応
  - `_run_generation_score_gate` が `native_render` を受け取り `render_engine` を渡す
  - `render_native_test` に `voice_speed_intro/body` を config 定数から渡す
- 各種コードレビュー修正（Codexリファクタ引き継ぎ）:
  - `image_generator.py`: 重複行削除・不要な `gc.collect()` 除去
  - `youtube_uploader.py`: `_close_media_upload` (no-op) を削除し `del media` に置換
  - `core/cta_policy.py`: Long目次のフードハードコード fallback を削除
  - `build_rebalanced_entries` 戻り値型アノテーションを `list[tuple]` に修正

---

## 2026-05-22

### Shortsループ優先・CTA制御・Long目次の運用反映

- 台本生成プロンプトに、Shortsは他動画誘導よりループ視聴を優先する方針を追加。
- Shorts本編の「次回は」「他の動画も見て」「チャンネル登録お願いします」系を生成前レビューで警告するように変更。
- `core/cta_policy.py` を追加し、同時生成時の「ネタ募集CTA: 許可 / 禁止」をアプリ側で付与。
  - Shortsのみ対象。
  - 生成区分が `新規` / `横展開` の場合のみ候補。
  - 5本以上の同時生成では最大1本だけ許可。
  - 5本未満、品質改善版、再挑戦は原則禁止。
- ネタ募集CTAを許可した場合、固定コメントが未指定ならネタ募集用固定コメントを自動差し込み。
- Longでは関連動画誘導、vidIQタイトル調整、説明欄YouTubeチャプター追加を許可。
- Longアップロード時、説明欄にチャプターがなければ `チャプター:` 行または既定章立てから `【目次】` を自動追加。
- `_meta/cta_policy.json` と `_meta/youtube_metadata.json` にCTA/Long方針を保存。
- テスト `tests/test_cta_policy.py` を追加。

---

## 2026-05-21

### YouTube同期・出力パス整理・台帳一元化・バグ修正

**アーキテクチャ変更 (commit 7be08a7)**:

- スケジュール管理を `upload_schedule_*.json` から `upload_records.json` 台帳ベースに移行
  - `schedule_from_records()` が `publish_status == "scheduled"` のレコードから派生ビューを生成
  - `sync_schedule_from_youtube()` で YouTube API を正としてローカル台帳を更新。チャンネル全件取得失敗時は既知 video_id のみでフォールバック
  - `rebalance_slots()` は変更リストを返すだけで書き込みを行わない（呼び出し側が YouTube + upload_records を更新）
  - 旧 `upload_schedule_*.json` は `output/000_legacy/` に退避
- 出力ディレクトリを整理
  - `output/000_data/` : `upload_records.json` / `uploaded_titles.txt`
  - `output/000_analytics/` : Analytics スコア JSON / TSV
  - `output/000_legacy/` : 旧スケジュールファイル退避
  - `core/output_paths.py` で絶対パスを集約。`config.py` の ENV 変数で変更可能
  - 旧パス (`output/upload_records.json` 等) は初回アクセス時に自動移行
- GUI のスケジュール画面を `upload_records` 由来の表示に統一
  - Analytics ウィンドウで閉じた後に `render()` が呼ばれて落ちる問題を `winfo_exists()` チェックで修正
  - API ステータス確認の多重実行を `_schedule_sync_running` フラグで抑制
  - リバランス時の移動内容をログ出力

**レビュー修正**:

- `schedule_from_records`: 同一スロットに重複レコードがあった場合、`setdefault` で黙って捨てていたのを `logging.warning` を出す明示判定に変更
- `save_upload_records`: `migrate_root_file` が内部で `ensure_output_dirs` を呼ぶため、直後の冗長な `os.makedirs` を削除
- `infer_video_type`: duration による Shorts 推定閾値を 180s → 60s に修正（YouTube 公式 Shorts 上限に合わせる）
- `rebalance_slots`: docstring を「変更リストを返すだけ・書き込みを行わない」と明記
- `sync_schedule_from_youtube` のフォールバック時にログを追加
- `_schedule_sync_running` フラグのレース修正: `sync_worker` と `detect_manual_published` でフラグのチェック・セットをスレッド起動前（メインスレッド）に移動

---

### vidIQ固定タグ更新・MP4なしアップロード候補除外・プロンプト改善

- `core/youtube_metadata.py` を追加し、vidIQキーワード分析に基づく YouTube タグ生成を一元化。
  - 共通タグに `食べ物 雑学`、`雑学 ショート`、`ゆっくり解説 食べ物`、`VOICEVOX解説`、`コンビニ 雑学`、`お菓子 雑学` などを採用。
  - `食べ物 豆知識` / `食べ物豆知識`、アニメ・漫画・ゲーム雑学、都市伝説、怖い話系タグを除外。
  - 寿司/サーモン、コンビニ/ファミチキ、お菓子、マック、トマト、コーラ、カレー等の題材別タグを自動追加。
  - タグ欄を500文字以内に調整し、実際に使ったタグを `_meta/youtube_metadata.json` に保存。
- `YouTubeアップ` の履歴選択画面で、アップロード可能な `.mp4` がない履歴を表示しないように変更。
- タイトル案プロンプトを更新。
  - 毒・危険視・薬だった系、袋・容器・穴・形・名前の理由、寿司/魚の価値逆転・名前の罠を優先。
  - viewsだけでなく平均視聴率・平均視聴時間・高評価率・登録者増を重視。
  - `雑学 ショート` などのSEO語はタグ・説明欄で補完し、タイトル本文へ不自然に入れないルールを追加。
- 台本生成プロンプトに「スワイプ率対策：ネタ入口パワー判定」を追加。
  - 台本化前に、ネタ名・タイトル・サムネ・冒頭1秒で見たくなるかを判定。
  - 弱い場合は名前の罠、昔と今の真逆、正体ズレ、袋・容器・包装など具体物へ切り口変更する。

---

## 2026-05-20（続き5）

### キャラ設定強化・冒頭パターン・尺判定更新・character_pattern/genre_group 追加

**台本生成プロンプト** (`core/script_generation_prompt.txt` および `local/` 版):
- キャラクタールール更新: ずんだもん=視聴者代表（驚き・疑問役）、めたん=食べ物裏側オタク気質として定義を追加
- 新セクション「冒頭話者パターン」: 外食チェーン/コンビニ/ファストフード/ファミレス/スイーツ/商品開発ではめたん冒頭を許可
- 新セクション「ギャグ制限ルール」: ギャグ・ツッコミは最大2回、冒頭の引き or ラストのオチのみ
- Shorts尺ルール更新: 理想42-48秒 / 許容39-50秒 / 51秒以上は警告 / 53秒以上は出し直し
- タイトルルール強化: 伝統/由来/歴史/本当の理由を避けるワードとして追記、感情動詞型（嫌われていた/出せなかった等）を追加
- フォーマットにキャラパターン/ジャンルフィールドを追加（local/はGit管理外）

**コード変更**:
- `core/parser.py`: キャラパターン/ジャンル の正規表現・META_TYPES・パース処理追加
- `core/analytics_score.py`: Shorts尺判定を42-48s理想/39-50s許容/51-52s警告/53s+needs_reviewに更新。to_tsvにcharacter_pattern/genre_group列追加
- `core/opening_quality.py`: 尺判定閾値を同様に更新。ChatGPT事前チェックの停止閾値を39s未満または53s超に変更
- `core/script_prompts.py`: TSVヘッダーにcharacter_pattern/genre_group追加
- `core/upload_records.py`, `core/youtube_analytics.py`: character_pattern/genre_group の記録・参照を追加
- `gui.py`: アップロード時・metadata.txt読み込み時にcharacter_pattern/genre_group保存。アナリティクスウィンドウにキャラパターン/ジャンル列追加。スケジュールウィンドウに生成区分/キャラ列追加

---

## 2026-05-20（続き4）

### 台本生成プロンプト: 冒頭3秒ルール（知的好奇心型）追加

- `core/script_generation_prompt.txt` および `core/prompt_parts/local/script_generation_prompt.txt` に新セクション「冒頭3秒ルール（知的好奇心型）」を追加。
  - 冒頭3行の型を定義: 1行目=意外な事実を断言、2行目=視聴者の疑問をめたんが代弁、3行目=理由・仕組みの入口
  - 「今日は〇〇について解説するのだ」「今回は〇〇の理由を紹介するのだ」を禁止パターンとして明記
  - 「ヤバい」「衝撃」などの雑な煽りだけに頼ることを禁止。構造として疑問→答えの入口を先に作る方針
  - ファミチキ袋・ドーナツの穴・バームクーヘン年輪・おにぎり包装の4例を追加
  - local/ はGit管理外のためコミットに含まれない

---

## 2026-05-20（続き3）

### `000_uploaded` を削除してもよい構造に変更

- アップロード記録の中央台帳 `output/upload_records.json` を追加。
- アップロード成功時に、各動画フォルダの `_meta/upload_record.json` と中央台帳の両方へ記録するように変更。
- アプリ起動時に既存の `output/000_uploaded/**/upload_record.json` を中央台帳へ移行。
- 固定コメント、公開予定変更、スロット詰め直し、Analytics補完は中央台帳を優先して参照するように変更。
- 中央台帳で公開予定動画を探すとき、同名タイトルより公開予定日時の一致を優先するよう修正。
- `output/000_uploaded/` はアップロード済み生成物の保管場所として扱い、削除しても `video_id`、公開予定、固定コメント状態、再生リスト登録結果、生成区分情報が残るようにした。
- README / SPEC を更新。

---

## 2026-05-20（続き2）

### タイトル案プロンプト大幅改善・台本プロンプトに生成区分追加

**タイトル案プロンプト（`core/script_prompts.py` `build_title_prompt()`）:**
- 分類にH「名前・発祥の勘違い」を追加（天津飯・ナポリタン・シュークリーム系を正しく分類）
- data_wait 動画の優先度を原則A止まりに制限（views 3000以上・likes 30以上・comments 3以上のみ暫定S可）
- 改善再挑戦枠を追加：既存食材でも条件A（views 1000以上+視聴率30〜49%）または条件B（views 500以上+like_rate 1.5%以上）を満たす場合は最大2案まで出力可
- 20案表を16列→12列に軽量化。選定理由・想定フック・冒頭1秒・注意点・事実確認ポイントはTOP5表に集約
- 型の内訳を20案表の直後に集計出力するルールを追加
- 自分ごと化タイトルの定義を明文化（勘違い破壊型・損回避型・日常の理由型・名前の罠型等）
- 新規開拓枠に品質チェックを追加（採点7点未満は出力しない）
- 30文字超タイトルの削除候補ワードを明示（「意外な」「知られざる」「本当の」等）
- 良いタイトル例を既存外の食材（天津飯・ちくわ・ナス等）に差し替え。例は構造参考のみと明記
- Long候補例にも既存食材流用禁止の注記を追加

**台本生成プロンプト（`core/script_generation_prompt.txt` および `core/prompt_parts/local/script_generation_prompt.txt`）:**
- フォーマット例に `生成区分` / `元動画` / `目的` フィールドを追加（説明付き）
- これにより Claude/ChatGPT 生成台本でも横展開・品質改善の記録が `upload_record.json` に保存されるようになった

**その他:**
- `core/ai_generator.py` と `main.py` に `generate_script()` がデッドコードである旨のコメントを追加

**注意:** `core/prompt_parts/local/` は Git 管理外のため、`local/script_generation_prompt.txt` の変更はコミットに含まれない。手元の環境で同ファイルを直接編集済み。

## 2026-05-20（続き）

### タイトル案プロンプトに自分ごと化・暫定横展開ルールを追加

- タイトル案生成プロンプトに、勘違い破壊型・損回避型・日常の理由型・名前の罠型など、視聴者が自分ごと化しやすい攻略帳型のタイトルルールを追加。
- 「食べ物の歴史」だけでなく「食べ物の勘違いを壊す」方向へ寄せる方針を追加。ただし20案中5〜7案程度に抑え、チャンネル本来の価値逆転型と混ぜる。
- `analysis_status=data_wait` の動画でも views / likes / like_rate / comments が強い場合は「暫定横展開候補」として扱うルールを追加。
- 既存・予約済みタイトルの近似重複禁止を強化し、同じ食材・同じ主張の言い換えを禁止。
- 20案の出力表に `優先度` / `型` / `想定フック` を追加。
- SPEC と食べ物用サンプルプロンプト部品を更新。

---

## 2026-05-20

### 横展開・品質改善版の追跡情報をAnalyticsに追加

- 台本メタ情報に `生成区分` / `元動画` / `目的` を追加。`新規` / `横展開` / `品質改善版` / `再挑戦` の判別に使う。
- 生成時の `metadata.txt` とアップロード時の `upload_record.json` に生成区分情報を保存。
- Analytics取得時に `output/000_uploaded/**/upload_record.json` を参照し、動画IDに紐づく生成区分情報をマージ。
- Analytics一覧とTSVに `生成区分` / `元動画` / `目的` を追加。
- README / SPEC に台本メタ情報とAnalytics表示仕様を追記。

---

## 2026-05-19（続き⑫）

### Analytics取得件数の見え方を改善

- Analytics一覧の各列ヘッダークリックで昇順/降順ソートできるように変更。
- Analytics画面のサマリーに、全件数だけでなく `公開 / 予約 / 分析 / 待ち` の内訳を表示。
- Analytics APIにまだ出ていない公開動画でも、YouTube Data APIの `statistics` から再生数・いいね数・コメント数を補完。
- 平均視聴率などが未取得の動画は、数値を補完してもスコア判定せず `data_wait` のまま扱う。
- SPEC に Analytics API と Data API のマージ仕様を追記。

---

## 2026-05-19（続き⑪）

### Codex/Claudeクレジット節約の作業ルールを明記

- `CLAUDE.md` に、常に Codex / Claude の利用クレジット消費を抑えて作業するルールを追加。
- 不要な長文出力、重複調査、過剰なファイル読み込み、不要な並列探索、同じ確認のやり直しを避ける方針を明記。
- アプリ側の動画生成・画像生成・LLMレビューは必要時だけ実行する方針を補足。YouTube APIは運用上必要なら使ってよいが、同じ取得や更新の無意味な繰り返しは避ける。

---

## 2026-05-19（続き⑩）

### Codex/Claude作業時のPowerShell文字化け対策を明記

- `CLAUDE.md` に、PowerShellで日本語ファイルを確認するときは `Get-Content` 直読みを避け、UTF-8指定のPython読み取り・`rg`・`git diff` を優先するルールを追加。
- PowerShell表示が文字化けした場合も、すぐにソース破損と判断せずUTF-8で読み直すよう明記。

---

## 2026-05-19（続き⑨）

### アップロード成功後に同一テーマのバックアップを自動削除

- 再生成時のバックアップ退避後、同一テーマのバックアップは最新1世代だけ残して古いものを自動削除。
- 生成時に `output/000_backups/` へ退避した同一テーマのバックアップを、アップロード成功後に自動削除するように変更。
- 削除対象は `output/000_backups/` 配下で、アップロード済みフォルダ名と一致または同じ接頭辞を持つディレクトリに限定。
- 実行ログに削除件数を表示。
- README / SPEC にバックアップ削除の挙動を追記。

---

## 2026-05-19（続き⑧）

### Longアップロード後の再生リスト自動追加に対応

- `.env` / `config.py` の `LONG_UPLOAD_PLAYLIST_NAME` に再生リスト名を設定すると、Long動画アップロード成功後に自チャンネルの再生リストへ自動追加するように変更。
- 未設定時の既定再生リスト名は `ロング動画`。
- 再生リストは名前完全一致で検索し、既に同じ動画が入っている場合は重複追加しない。
- 追加結果を `_meta/upload_record.json` の `playlist_*` フィールドに保存。
- 実行ログに `再生リスト登録完了` / `再生リスト登録済み` / `再生リスト登録失敗` を明示。
- README / SPEC に設定方法と挙動を追記。

---

## 2026-05-19（続き⑦）

### ドキュメント更新ルールを明文化

- `CLAUDE.md` に、仕様・画面・プロンプト・設定・YouTube連携・Analytics判定・生成フローを変更した場合はドキュメント更新を必須にする運用ルールを追加。
- 最新仕様は `SPEC.md`、大きめの変更履歴は `CHANGELOG.md`、セットアップやAPIキー・設定に関わる変更は `README.md` も更新する方針を明記。

---

## 2026-05-19（続き⑥）

### アナリティクス横展開候補の選定ルールを厳格化

`core/analytics_score.py` の採点ロジックを更新。

- **最低視聴率ライン**: Shorts 45% / ShortLong 50% 未満では `横展開` に昇格しない。
- **判定保留フラグ** (`is_provisional`): views < 500 かつ公開後24時間未満の動画は横展開アクションに `(判定保留)` を付与。
- **登録者純増 >= 1**: 弱いスコアに `・登録導線あり` を補足表示（>= 2 は引き続き強い横展開候補）。
- **コメント >= 1**: `弱い` / `要見直し` スコアに `・反応あり` を補足表示。
- **高エンゲージメント・低視聴率**: like率 >= 1.5% かつ最低ライン未達 → `テーマ有望・構成改善`。
- **views 上位20% 昇格ロジック**: 最低視聴率ラインと `is_provisional` チェックを追加（viewsだけで横展開しない）。
- TSV 出力に `is_provisional` カラムを追加。
- Longは登録者増だけで `横展開` にせず、CTR 8%以上かつ平均視聴率40%以上を横展開条件にする。
- Analytics画面に `分析状態` / `判定保留` 列を追加。
- タイトル案プロンプトの実績データTSVヘッダーに `publish_status` / `analysis_status` / `is_provisional` を追加。
- SPEC の動画スコア判定ルールを最新実装に合わせて更新。

---

## 2026-05-19（続き⑤）

### Long画像節約モードを追加

- `config.py` に `MAX_BACKGROUNDS_LONG_BUDGET = 16` を追加。
- GUI オプション行に **「Long節約」チェックボックス**（デフォルト OFF）を追加。ON にすると Long の背景生成上限を 16 枚に制限。Shorts には影響なし。
- `main.py`: `run_pipeline()` に `long_budget_mode` パラメータを追加。上限超過シーンは自動的に前の背景を継続使用。
- **明示的再利用記法**: 台本の背景行に `背景: 前と同じ` と書くとカウントを消費せず前の背景を継続する（新規生成なし）。
- 台本生成プロンプトに節約モードの記法説明を追記。
- SPEC / README を更新。

---

## 2026-05-19（続き④）

### Long台本生成ルールを厳格化・Long向き題材ルールを追加

- `core/prompt_parts/local/script_generation_prompt.txt` に **Long 生成の最低尺ルール（絶対厳守）** セクションを追加。
  - Long指定時は必ず150〜200セリフ。150未満はLongとして不合格。
  - シーン数 35〜45、1シーン3〜5セリフ、チャプター5〜6章を明示。
  - 5分未満になりそうな題材はShortLong扱い（Longにしない）。
- **Long向き題材ルール** セクションを追加。「章を増やせる題材」だけをLongにするルールと、Shorts向きとの判別基準を明記。
- 自己チェックに Long専用チェック項目を追加（セリフ数・シーン数・チャプター構成・引き伸ばし禁止）。

---

## 2026-05-19（続き③）

### 固定コメント「未投稿だけ」フィルタのバグ修正

- `fixed_comment_thread_id` が未記録でも `fixed_comment_pinned_at` が設定済みなら完了扱いにする。
- YouTube Studio 等で外部ピン留めしアプリで記録した場合も、「未投稿だけ」チェック時に正しく非表示になる。

---

## 2026-05-19（続き②）

### スケジュールダイアログを開くたびにYouTubeと自動同期

- `📅 スケジュール` を開くと自動的に YouTube API でステータスを確認し、ローカルとの差異があれば確認ダイアログを表示するように変更。
- `public` になっていた動画は手動公開済みとして処理（予約スロット削除・`uploaded_titles.txt` 追記）。
- ローカルと YouTube の `publishAt` が 1 分以上ズレている場合はローカルスケジュールと `upload_record.json` を YouTube 側に合わせて更新。
- 差異がない場合はログに「差異なし」とだけ表示して静かに完了。
- `core/youtube_uploader.py` に `get_video_statuses()` 関数を追加（50件バッチ、privacyStatus + publishAt を返す）。

---

## 2026-05-19（続き）

### Long サムネイル A/B テストを無効化オプションに変更

- `config.py` に `LONG_THUMBNAIL_AB_TEST`（デフォルト `False`）を追加。
- `False` のときは Variant A のみ生成し、`thumbnail_ab_test.json` を書かないように変更。
- `True` にすると従来どおり A/B/C 3バリアント生成・マニフェスト保存。
- GUI のオプション行に「LongサムネAB」チェックボックスを追加（デフォルト OFF）。チェックすると A/B/C 3枚生成に切り替わる。
- 背景再利用フローでのサムネイル再生成時も AB テスト設定が正しく引き継がれるよう修正。

---

## 2026-05-19

### アナリティクスの取得件数を全動画対象に変更

- Analytics API の取得期間内に再生実績がない動画も含め、チャンネル全動画を対象にスコアリングするように変更。
- Data API の uploads プレイリストから全動画 ID をページネーション付きで取得し、Analytics データと結合するように変更。
- 動画の `publish_status`（published / scheduled / private / unlisted）を判定し、Analytics 画面に表示するように変更。予約公開中（private ＋ publishAt が未来）は `scheduled` として扱う。
- `analysis_status`（analyzable / data_wait / scheduled / excluded）でスコアリングの対象外を分類し、予約中・非公開はスコア「未計測」・「対象外」として表示するように変更。
- 61〜120 秒の動画を `ShortLong` タイプとして Shorts / Long と別に判定し、専用スコアリング閾値を適用するように変更。
- `views == 0` はスコア「未計測・データ待ち」として処理するように変更。
- 登録者純増 ≥ 2 でスコアを最低 B に引き上げ、さらに平均視聴率 ≥ 60% なら action を「横展開」に変更。
- 高評価率 ≥ 1.5% かつスコアが C/D の場合は action を「テーマ有望・冒頭/構成改善」に変更。
- 再生数上位 20%（80 パーセンタイル）かつ平均視聴率 ≥ 65% の場合は action を「横展開・微改善」に変更。

### スケジュール画面にスロット詰め直し機能を追加

- `📅 スケジュール` に「スロット詰め直し」ボタンを追加。未来の予約スロット全件を現在から最速の空きスロットに前詰めするように変更。
- `upload_record.json` の `publish_at` から video_id を特定し、YouTube 側の公開予定時刻・`upload_schedule_*.json`・`upload_record.json` を一括更新。video_id が見つからない場合はスケジュール JSON のみ更新して警告ログを出す。

### スケジュール画面に絞り込みフィルターを追加

- デフォルト表示を「予定のみ」に変更（済みは非表示）。
- ラジオボタン（すべて / Shorts / Long）で種別ごとに絞り込めるように変更。
- 「済みも表示」チェックボックスで済みエントリーを表示・非表示できるように変更。
- フィルター変更に連動して下部のカウント（合計 / 予定 / 済）も更新されるように変更。

### Ollamaレビュー失敗時に処理中止するよう変更

- Ollama冒頭レビューが接続エラーなどで失敗した場合、ローカル判定へフォールバックして続行せず、レビュー結果を保存して生成処理を中止するように変更。
- Ollama APIが応答していない場合は、レビュー前に `ollama serve` の自動起動を試みるように変更。
- 自動起動してもAPIが応答しない場合は、レビュー結果を保存して生成処理を中止する。
- 冒頭スコア表示に使用モデル名を追加。
- GUIログやAnalytics画面の尺評価表示を日本語化。
- 複数台本の一括生成では、生成開始前に全台本の冒頭スコア・推定尺チェックを先に実行し、要確認がある場合は生成へ進まないように変更。

### 主要ボタンにホバー説明を追加

- メイン画面の生成、停止、LLM/尺チェック、AI台本作成、AIタイトル案、画像確認、YouTubeアップ、スケジュール、アナリティクスなどにツールチップを追加。
- Analytics画面の取得、評価一覧コピー、AI分析用コピーにもツールチップを追加。
- 複数台本処理中に、実行ログラベル横へ「何本中何本完了」形式の進捗表示を追加。
- アップロード済み履歴の `script.txt` にある固定コメントを既存動画へ投稿するボタンを追加。投稿成功後は `upload_record.json` にコメントIDを記録し、二重投稿を避ける。
- 固定コメント投稿前に動画状態を確認し、非公開・存在しない動画・子ども向け設定の動画は投稿せずスキップするように変更。
- 固定コメント投稿成功時に、確認用の一覧画面を表示し、通常動画URLを開けるように変更。
- 固定コメント対象一覧に「未投稿だけ」「公開済みだけ」フィルタを追加し、ピン留め済みの手動記録を残せるように変更。
- 固定コメント投稿後の一覧画面からYouTube Studioコメントボタンを削除し、通常動画URLを開くボタンだけに変更。
- Analytics画面とTSVに高評価率を追加し、AI分析用コピーとタイトル案プロンプトへ実績サマリーを自動で付けるように変更。
- `Longタイトル案` ボタンを追加し、Long候補だけを出すタイトル案プロンプトをコピーできるように変更。
- 既存の `AIタイトル案` ボタン表示を `Shortsタイトル案` に変更。
- LLM/尺チェック後のAI修正依頼文を、問題がない台本も含めて全台本を返す指示に変更し、元台本本文を添付するように変更。
- 冒頭スコアがローカルルール判定だけで通過した場合も `model review:local-rule` を表示し、ChatGPT生成前スコアにも使用モデルを表示するように変更。
- スケジュール画面から予約投稿済み動画の公開予定日時を変更できるようにし、YouTube側の `publishAt`、アプリ内スケジュール、`upload_record.json` を同時に更新するように変更。
- 公開予定変更の変更先時刻を、既存のアップロード時刻ルール（Shorts 7/12/19時、Long 平日21時・土日12/21時）に限定。
- 公開予定変更の日時指定を手入力から日付・時間のプルダウン選択に変更。
- 公開予定変更で同じ種別の既存予定枠に移動する場合、エラーではなく2本の公開予定を入れ替えられるように変更。
- 固定コメント投稿前の動画状態確認に失敗した場合は、誤投稿防止のため投稿処理を中止するように変更。
- README / SPEC にAPIキー・YouTube OAuthの取得手順と、`config.py` / `.env` で変更できる主な設定一覧を追記。
- タイトル案プロンプトを、固定ルールと既存タイトル・実績データなどの差し込み情報が分かる構造に整理。
- タイトル案プロンプトのネタ固有部分を `core/prompt_parts/` に分離し、実績データ欄・重複チェック・既存食材リストを差し替えやすく変更。
- 個人用プロンプト差し替え欄 `core/prompt_parts/local/` をGit管理外にし、同名ファイルがあればローカル側を優先して読み込むように変更。
- `core/prompt_parts/local/script_generation_prompt.txt` がある場合は、台本生成プロンプト本体もローカル側を優先するように変更。
- 共有用のサンプル台本 `samples/scripts/food_shorts_sample.txt` を追加。
- 食べ物用プロンプト設定の復元サンプルを `samples/prompt_parts/food/` に追加。
- 初回クローンでも食べ物用設定でそのまま動くように、Git管理側の既存食材リストを食べ物用に戻した。
- README / SPEC の初回セットアップ手順に、別ジャンル用 `local/` 差し替えと食べ物用設定の復元手順を追加。
- 初回セットアップのプロンプト設定確認を必須手順として明記。
- SPEC にAI編集者向けルールを追加し、ネタ固有プロンプト変更は `core/prompt_parts/local/` を編集するよう明記。
- SPEC のシステム構成に `core/prompt_parts/`、`core/prompt_parts/local/`、`samples/` を追記。
- SPEC 全体を実装に合わせて見直し、パイプライン順、Shorts尺判定、冒頭レビュー停止条件、Ollama設定、VOICEVOX末尾処理、GUI主要機能の記述を更新。

### AIタイトル案プロンプトを実績データ横展開型に変更

- `AIタイトル案` ボタンで、直近の `output/analytics_score_*.tsv` を自動でタイトル生成プロンプトへ差し込むように変更。
- タイトル案の評価に YouTube Analytics の `views`、`average_view_duration`、`average_percentage_viewed`、`subscribers_net`、`likes`、`comments` を反映。
- `ctr` / `impressions` が 0 または空欄の場合は評価に使わず、視聴率・視聴時間・登録者増を優先するルールを追加。
- 20案の出力表に `横展開元` と `実績根拠` を追加。TOP5選定にも必須化。
- 実績根拠には数値を最低1つ以上入れるルールを追加。
- 実績横展開は12〜15案、新規開拓枠は5〜8案を目安に変更。同じ横展開元から最大4案・TOP5は最大2案に制限。
- タイトル案に `既知度` と `既知ネタ回避` の判定を追加。既知度高の案は出力・TOP5採用しないルールを追加。
- Long候補にも実績データ横展開を強制し、3幕構成・5〜10分へ伸ばせる背景を評価する専用ルールを追加。

### 台本プロンプトに既知ネタ深掘りルールを追加

- 台本の中心が「誰でも知っている話」や単なる商品特徴説明にならないよう、既知ネタ深掘りルールを追加。
- 既知度が高いテーマは、開発背景、改良の歴史、味や香りの仕組み、誤解されているポイントへ中心をズラすように変更。

### タイトル・サムネ・冒頭ルールを強化

- 抽象表現だけのタイトル・サムネを禁止。タイトルは理由・経緯、サムネは一番強い事実という役割分担を明確化。
- サムネに書いた衝撃ワードを冒頭5秒以内に回収するルールを追加。
- Longサムネは8〜16文字、最大20文字、食材名 + 逆転ワードを基本に変更。

---

## 2026-05-18

### Longアップスロットを毎日21時・土日は追加で12時に変更

- Long のアップロードスロットを「毎日 21:00 + 土日のみ 12:00」に変更。
- `upload_scheduler.py` の定数を `LONG_SLOTS_WEEKDAY = [21]` / `LONG_SLOTS_WEEKEND = [12, 21]` に変更。

### 出力フォルダ構造をサブフォルダに整理

- 生成物を `_meta/`（レビュー結果・メタデータ）と `thumbnails/`（サムネイル画像）に分離。
- `opening_review.json`、`duration_review.json`、`final_review.json`、`upload_record.json` などすべて `_meta/` へ移動。

### 台本生成プロンプトに既存タイトル重複禁止リストを追加

- `Shortsタイトル案` / `Longタイトル案` のプロンプトに、`output/` 配下のタイトルと `uploaded_titles.txt` をまとめた重複禁止リストを自動で差し込むように変更。

### ScriptParser を共有定数化・parse_string の tempfile 廃止

- `ScriptParser.META_TYPES` を `gui.py` / `main.py` 共通の判定定数として使うように変更。
- `parse_string()` をメモリ内処理に変更（tempfile を使わない）。

---

## 2026-05-17

### YouTube アナリティクス GUI を追加

- `📊 アナリティクス` ボタンを追加。YouTube Analytics API から動画・チャンネル指標を取得し、S/A/B/C/D スコアで評価する画面を追加。
- スコア行に色付き表示（強い＝緑・注意＝黄・低い＝赤）。TSV コピー・AI 分析用コピー・`output/analytics_score_YYYYMMDD.{json,tsv}` エクスポートに対応。

### Ollama 冒頭レビューを厳格化・項目別スコア対応

- 冒頭レビューを項目別スコア形式に変更。
- 冒頭スコアが 80 未満の場合はパイプラインを中止するように変更（しきい値を 60 → 80 へ引き上げ）。

### 生成前危険チェック・Shorts 尺予測・完了後総合判定を追加

- 生成開始前に危険チェック（NGワード・尺外れ）を実行し、問題があれば中止するように変更。
- Shorts の推定尺を冒頭 2.0 倍速 / 本編 1.65 倍速で計算してログ出力するように変更。
- 全動画の生成完了後に冒頭スコア・尺・最終レビューを並べた総合判定をログ表示するように変更。
- アップロード確認ダイアログにスコア列（冒頭 / 尺 / 最終）を追加。

### 説明文の VOICEVOX クレジット手書き行を自動除去

- 説明文に手書きで入っている VOICEVOX クレジット行を自動で除去し、警告なしに `_VOICEVOX_CREDIT` / `_CHANNEL_FOOTER` を末尾に付与するように変更。

### アップロード完了後に MP4 を自動削除

- アップロード成功後、`output/` 内の MP4 ファイルを自動で削除するように変更（容量節約）。

### FPS を 60 → 30 に変更・音声末尾処理を改善

- `config.py` の `VIDEO_FPS` を 60 → 30 に変更。
- `VOICE_TAIL_SAFETY` / `INTER_DIALOGUE_GAP` をフレーム数定数から秒数定数（FPS 非依存）に変更。
- `VOICE_TAIL_SAFETY_SEC = 0.5s` / `INTER_DIALOGUE_GAP_SEC = 0.2s` に設定。

### サムネイル生成を nanobanana2 に固定

- 背景と統一するため、サムネイル生成モデルを常に `nanobanana2` に固定。

---

## 2026-05-16

### 投稿済みタイトルを uploaded_titles.txt に永続保存

- アップロード完了後、タイトルを `output/uploaded_titles.txt` に追記するように変更。
- `Shortsタイトル案` / `Longタイトル案` の重複禁止リストに `uploaded_titles.txt` も含めるように変更。

### タイトル一覧のクリップボードコピーボタンを追加

- `output/` 配下の全テーマタイトルをクリップボードへ一括コピーするボタンを追加。

### タイトル体言止め禁止ルールを強化

- 台本・タイトル案プロンプトの体言止め禁止ルールを強化。動詞・形容詞止めを必須とするよう変更。

---

## 2026-05-15

### YouTube 予約投稿・スケジュール管理を追加

- `YouTubeアップ` から複数動画を一括予約投稿できるように変更。Shorts は毎日 7:00 / 12:00 / 19:00、Long は毎日 21:00 に自動割り当て。
- `📅 スケジュール` ボタンを追加。予約済み一覧確認・削除・手動公開済み処理に対応。
- スケジュールを `output/upload_schedule_shorts.json` / `upload_schedule_long.json` に永続化。

### 音声末尾無音を自動付加

- VOICEVOX 生成 WAV の末尾に 0.5 秒の無音を Python で直接付加するように変更（`postPhonemeLength` API が効かないため）。

### Shorts 品質改善・パーサー強化

- Shorts の台本パラメータ（行数目標・尺目標）を実測値ベースに更新。
- `ScriptParser` を強化し、区切り記号（`━━ 動画1 ━━`）による複数台本分割に対応。

---

## 2026-05-14

### BGM を固定曲に変更・ワークフロー制御ボタンを追加

- BGM を BGMer「のほほん」に固定し、生成時に自動追加するように変更。
- 作業中止ボタンを追加し、生成処理を即時キャンセルできるように変更。

### Nano Banana クォータ枯渇時の対応を追加

- 画像生成で Nano Banana のクォータが枯渇した場合にエラーを適切に処理してリトライを止めるように変更。
