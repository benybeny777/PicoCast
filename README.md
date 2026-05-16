# YMM4 Auto Video Factory

「ずんだもんとめたんの食べ物雑学堂」向けに、食べ物雑学の解説動画を台本から YMM4 プロジェクトまで自動生成するツールです。台本の整形、VOICEVOX 音声、背景画像、サムネイル、立ち絵、字幕、固定 BGM、YouTube アップロード補助までまとめて扱います。

## 主な機能

- 台本貼り付けから `.ymmp` を自動生成
- Shorts / ロングを `動画形式:` から自動判定
- `━━ 動画1 ━━` や `動画形式:` が複数ある台本を分割して一括生成
- YouTube NG ワードをマイルド表現へ自動置換
- VOICEVOX 音声は Shorts: 冒頭2.0倍速・本編1.65倍速、ロング: 冒頭1.6倍速・本編1.35倍速で生成
- 音声末尾無音は速度比例（`0.05 × speed_scale` 秒）+ 2 フレーム安全余白、セリフ間隔 6 フレーム（約 0.1s）
- 背景指定がセリフの後に来る台本も自動で補正
- 台本本編は `# Scene ...` 見出しでシーンごとに生成し、各シーンに背景・必要なテロップ・会話をまとめる
- 背景は Shorts 6〜9 枚（3〜5秒ごとの見た目変化が理想）・ロングは5〜7秒に1枚を目安に配置
- 追加テロップはYMM4字幕と重複させず、短い要約・強調だけに制限
- 立ち絵より上のレイヤーに字幕を配置
- BGMer「のほほん」を固定 BGM として自動追加
- 生成履歴から複数選択して再生成 / YouTube アップロード
- 画像確認画面でサムネイル・背景を確認し、選択した画像だけ再生成
- `AI台本作成` ボタンで食べ物雑学特化の台本生成プロンプトをコピー
- `AIタイトル案` ボタンで既存タイトル・既存食材の重複回避付きタイトル案プロンプトをコピー
- 作業中止ボタンで生成処理を即時キャンセル扱いにし、戻ってきた外部API結果は破棄
- YouTube 予約投稿: 毎日 0:00 / 7:00 / 12:00 / 19:00 (JST) のスロットに自動割り当て
- Shorts / Long を独立したスケジュールで管理（同一スロットに両方投稿可）
- 「📅 スケジュール」ボタンでアップロード予定・済みの一覧確認・削除・手動公開済み処理
- 「📊 アナリティクス」ボタンで YouTube Analytics API から動画単位・チャンネル全体の指標を取得
  - 期間選択（7日/28日/90日）、再生数・インプレ・CTR・平均視聴時間・視聴率・高評価・コメント・登録者増減を一覧表示
  - 「📋 AI分析用にコピー」でタブ区切りデータをクリップボードへコピー（Claude/ChatGPT 等に貼り付け可）

## セットアップ

1. VOICEVOX をインストール
2. YukkuriMovieMaker v4 をインストール
3. `.env` に `GOOGLE_API_KEY=...` を設定
4. Python 依存を入れる

```bash
pip install requests google-genai python-dotenv pywinauto Pillow google-api-python-client google-auth-oauthlib
```

## 起動

```bash
python gui.py
```

## 基本の使い方

1. `AIタイトル案` ボタンでタイトル案作成プロンプトをコピーし、候補を作成
2. `AI台本作成` ボタンで台本作成プロンプトをコピーし、採用タイトルから台本を作成
3. GUI の台本欄に貼り付け
4. `🎬 生成` を押す
5. 必要なら `画像確認` で画像を見直す
6. `動画出力` で YMM4 から MP4 を書き出す
7. `YouTubeアップ` で履歴から動画を選んでアップロード

## 台本フォーマット

```text
動画形式: Shorts
動画タイトル: タイトル
サムネ文字: ヤバい
説明文: YouTube説明文（VOICEVOXクレジット不要・自動付与）
タグ: ずんだもん,ゆっくり解説,雑学

背景: 場面説明、漫画風、画面上部に"テロップ"を描画
ずんだもん(ノーマル): セリフ
四国めたん(ツンツン): セリフ
```

複数動画をまとめて貼る場合は、次のような区切りに対応しています。

```text
━━ 動画1：ショート版 ━━
動画形式: Shorts
...

━━ 動画2：ロング版 ━━
動画形式: ロング
...
```

または `---` 区切りでも一括生成できます。

## 固定 BGM

固定 BGM は [BGMer「のほほん」](https://bgmer.net/music/093) のロング版を使います。

- 音源: `assets/bgm/nohohon_long_BPM97.mp3`
- 設定: `config.py`
- 音量: `BGM_VOLUME = 15.0`
- レイヤー: `BGM_LAYER = 2`

BGM ファイルが存在しない場合は、生成を止めずに BGM なしで続行します。

## 出力構成

```text
output/<動画タイトル>/
├─ <動画タイトル>.ymmp
├─ script.txt
├─ metadata.txt
├─ thumbnail.png
├─ audio/
└─ backgrounds/
```

アップロード済みの履歴は `output/000_uploaded/` に移動します。

スケジュールは以下に保存されます（Git 管理外）:

```text
output/upload_schedule_shorts.json
output/upload_schedule_long.json
```

YouTube Studio 側で予約動画を手動公開した場合は、`📅 スケジュール` 画面で該当行を選び、`手動公開済みにする` を押します。アプリ側の予約スケジュールから削除し、`output/uploaded_titles.txt` にタイトルを追記して、以後のタイトル重複回避に使います。

## レイヤー構成

| レイヤー | 用途 |
|---:|---|
| 0 | 背景画像 |
| 1 | トランジション |
| 2 | 固定 BGM |
| 3-4 | 立ち絵 |
| 6 | セリフ字幕 / 音声 |

## 音声タイミング

Shorts / Long ともに、VOICEVOX の WAV 実長へテンプレートの `AdditionalTime` 0.3 秒を加え、さらに `VOICE_TAIL_SAFETY_FRAMES = 2` フレームを音声アイテム長に足します。次のセリフ開始までは `INTER_DIALOGUE_GAP_FRAMES = 6` フレーム空けます。

WAV 末尾には `0.05 × speed_scale` 秒の無音を直接書き込みます（Shorts 冒頭 2.0x なら 0.1s）。高速音声で末尾フォネームが切れるのを防ぎます。

音声速度は Shorts が冒頭 `VOICE_INTRO_SPEED_SCALE_SHORTS = 2.0`・本編 `VOICE_SPEED_SCALE_SHORTS = 1.65`、ロングが冒頭 `VOICE_INTRO_SPEED_SCALE_LONG = 1.6`・本編 `VOICE_SPEED_SCALE_LONG = 1.35` です。冒頭判定は `VOICE_INTRO_FAST_SECONDS = 5.0` 秒以内に開始するセリフです。

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

## 主要設定

| 設定 | 内容 |
|---|---|
| `VOICE_SPEED_SCALE_SHORTS` | Shorts本編のVOICEVOX音声速度。現在は `1.65` |
| `VOICE_INTRO_SPEED_SCALE_SHORTS` | Shorts冒頭のVOICEVOX音声速度。現在は `2.0` |
| `VOICE_SPEED_SCALE_LONG` | ロング本編のVOICEVOX音声速度。現在は `1.35` |
| `VOICE_INTRO_SPEED_SCALE_LONG` | ロング冒頭のVOICEVOX音声速度。現在は `1.6` |
| `VOICE_INTRO_FAST_SECONDS` | 冒頭高速化の対象秒数。現在は `5.0` |
| `MAX_BACKGROUNDS_SHORTS` | Shortsの背景生成上限。現在は `9` |
| `MAX_BACKGROUNDS_LONG` | ロングの背景生成上限。現在は `90` |
| `BGM_PATH` | 固定 BGM のパス |
| `BGM_VOLUME` | 固定 BGM の音量 |
| `BGM_LAYER` | 固定 BGM のYMM4レイヤー |

## 注意

- `output/`, `.env`, `client_secrets.json`, `token.json` は Git 管理外です。
- YouTube アップロードには Google OAuth 用の `client_secrets.json` が必要です。
- YMM4 の自動動画出力は GUI 操作の自動化なので、YMM4 側のUI変更で調整が必要になることがあります。
