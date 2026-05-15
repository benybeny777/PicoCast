# YMM4 Auto Video Factory

ずんだもん / 四国めたんの解説動画を、台本から YMM4 プロジェクトまで自動生成するツールです。台本の整形、VOICEVOX 音声、背景画像、サムネイル、立ち絵、字幕、固定 BGM、YouTube アップロード補助までまとめて扱います。

## 主な機能

- 台本貼り付けから `.ymmp` を自動生成
- Shorts / ロングを `動画形式:` から自動判定
- `━━ 動画1 ━━` や `動画形式:` が複数ある台本を分割して一括生成
- YouTube NG ワードをマイルド表現へ自動置換
- VOICEVOX 音声を 1.5 倍速で生成
- 音声末尾に 20 フレームの安全余白を付け、セリフ間隔を 25 フレーム確保
- 背景指定がセリフの後に来る台本も自動で補正
- 背景は Shorts 3〜5 枚・ロング 5〜7 枚を目安に配置
- 立ち絵より上のレイヤーに字幕を配置
- BGMer「のほほん」を固定 BGM として自動追加
- 生成履歴から複数選択して再生成 / YouTube アップロード
- 画像確認画面でサムネイル・背景を確認し、選択した画像だけ再生成
- 作業中止ボタンで生成処理をキャンセル
- YouTube 予約投稿: 毎日 0:00 / 7:00 / 12:00 / 19:00 (JST) のスロットに自動割り当て
- Shorts / Long を独立したスケジュールで管理（同一スロットに両方投稿可）
- 「📅 スケジュール」ボタンでアップロード予定・済みの一覧確認・削除

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

1. `📋 VidIQ` ボタンで台本作成プロンプトをコピー
2. ChatGPT / VidIQ などで台本を作成
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

## レイヤー構成

| レイヤー | 用途 |
|---:|---|
| 0 | 背景画像 |
| 1 | トランジション |
| 2 | 固定 BGM |
| 3-4 | 立ち絵 |
| 6 | セリフ字幕 / 音声 |

## 音声タイミング

Shorts / Long ともに、VOICEVOX の WAV 実長へテンプレートの `AdditionalTime` 0.3 秒を加え、さらに `VOICE_TAIL_SAFETY_FRAMES = 20` フレームを音声アイテム長に足します。次のセリフ開始までは `INTER_DIALOGUE_GAP_FRAMES = 25` フレーム空けます。

## 立ち絵テンプレート

四国めたんの既定ポーズは、`core/character_templates.json` で両手とも普通手に設定しています。YMM4のPSDレイヤーIDでは、右手が `n16`、左手が `n24` です。目レイヤーはGit版の既定状態を維持しています。

## 主要設定

| 設定 | 内容 |
|---|---|
| `VOICE_SPEED_SCALE` | VOICEVOX 音声速度。現在は `1.5` |
| `MAX_BACKGROUNDS` | 1動画あたりの背景生成上限。現在は `7` |
| `BGM_PATH` | 固定 BGM のパス |
| `BGM_VOLUME` | 固定 BGM の音量 |
| `BGM_LAYER` | 固定 BGM のYMM4レイヤー |

## 注意

- `output/`, `.env`, `client_secrets.json`, `token.json` は Git 管理外です。
- YouTube アップロードには Google OAuth 用の `client_secrets.json` が必要です。
- YMM4 の自動動画出力は GUI 操作の自動化なので、YMM4 側のUI変更で調整が必要になることがあります。
