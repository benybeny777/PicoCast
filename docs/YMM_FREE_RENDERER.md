# ffmpeg/native レンダラー実装メモ

この文書は、YMM4を使わずにffmpeg/nativeでMP4を出力するレンダラーの引き継ぎメモです。

## 目的

既存のYMM4生成フローを壊さず、Shorts本番レンダリングをffmpeg/nativeで行うための経路です。
YMM4プロジェクトは保険・確認・再編集用に引き続き生成します。

- 背景画像
- 静止立ち絵（PSD抽出キャッシュ/PNG）
- VOICEVOX音声
- 白文字 + 話者別キャラ色フチ + 黒外フチ + 必要時の半透明黒帯
- BGM
- ffmpegによるMP4出力
- 簡易口パク
- 周期まばたき

感情タグに応じた表情差分、音量ベース口パク、微動はまだ未実装です。

## GUI入口

実装箇所: `gui.py`

### 通常生成（Shorts）

通常の生成フローでShortsを作ると、`DEFAULT_SHORTS_RENDER_ENGINE = "native"` によりnativeレンダリングが自動選択されます。

流れ:

1. 台本をテキスト欄に貼る
2. 通常の生成ボタンを押す
3. `run_pipeline()` で台本、音声、背景、サムネ、YMM4プロジェクトまで生成
4. 生成フォルダを特定
5. `core.native_renderer.render_native_test()` を実行
6. 生成フォルダ直下に `{履歴フォルダ名}_native.mp4` を出力

注意:

- 現段階では `run_pipeline()` 自体はYMM4プロジェクトも保存します。
- native選択時は、YMM4アプリを起動して動画出力する処理は走りません。
- 画像生成や音声生成も走るため、通常生成と同じくらい時間がかかります。

### YMMなしMP4化(test)

既存履歴からffmpeg処理だけを単体実行します。

流れ:

1. `YMMなしMP4化(test)` を押す
2. 履歴選択ダイアログで既存履歴を選択
3. 選択した履歴フォルダの `script.txt`、`audio/`、`backgrounds/` を読む
4. `core.native_renderer.render_native_test()` を実行
5. 各履歴フォルダ直下に `{履歴フォルダ名}_native.mp4` を出力

これは素材生成を飛ばすため、字幕やffmpeg合成の調整確認に使います。

## レンダラー本体

実装箇所: `core/native_renderer.py`

主関数:

```python
render_native_test(
    output_dir: str,
    progress_callback=None,
    voice_speed_intro: float | None = None,
    voice_speed_body: float | None = None,
) -> NativeRenderResult
```

入力として期待する履歴フォルダ構成:

```text
output/{履歴名}/
  script.txt
  audio/
    001_001_セリフ.wav
    001_002_セリフ.wav
  backgrounds/
    bg_001_001.png
    bg_002_001.png
```

出力:

```text
output/{履歴名}/{履歴名}_native.mp4
output/{履歴名}/_native_test/
  segment_0000_thumbnail.mp4
  segment_0001.mp4
  subtitle_0001.ass
  segment_concat.txt
```

`_native_test/` は中間生成物です。現状は残します。不要なら後で自動削除設定を追加できます。

## ffmpeg処理

`config.py` に以下を追加しています。

```python
FFMPEG_BIN = os.environ.get("FFMPEG_BIN", "ffmpeg")
```

通常はPATH上の `ffmpeg` を使います。必要なら `.env` で変更できます。

```text
FFMPEG_BIN=C:\path\to\ffmpeg.exe
```

処理順:

1. `audio/*.wav` をファイル名順に読み、各WAVの長さを取得する
2. `backgrounds/bg_*.png` を音声の背景番号に合わせて割り当てる
3. 各セリフごとにASS字幕を生成し、背景・立ち絵・口パク・まばたきと合成したセグメントMP4を作る
4. Shortsでは `thumbnails/thumbnail.png` があれば先頭1フレームのサムネイルセグメントを挿入する
5. セグメントをconcatし、BGMを合成して `{履歴フォルダ名}_native.mp4` に上書き出力する

## 字幕仕様

字幕はASS形式で焼き込みます。

実装箇所:

- `_dialogue_chunks()`
- `_caption_style()`
- `_write_subtitles()`

話者別スタイル:

- ずんだもん: `Zundamon`、白文字 + 濃緑の内フチ + 黒外フチ
- めたん/四国めたん: `Metan`、白文字 + 濃ピンク紫の内フチ + 黒外フチ
- 判別不能: `Default`、白文字 + 黒フチ

Shortsの通常字幕は背景に左右されない可読性を優先します。半透明黒帯を有効にした場合も残し、キャラ差は本文色ではなくフチ色で表現します。

台本の話者名からスタイルを判定します。

台本から取れる字幕数がWAV数より少ない場合は、WAVファイル名の3要素目を字幕として補完します。

例:

```text
001_002_何がヤバいのよ.wav
```

この場合、補完字幕は `何がヤバいのよ` になります。

## サイズ判定

`_video_size()` で解像度を決めます。

- 履歴フォルダ名が `[Shorts]` / `[SHORT]` で始まる場合: `1080x1920`
- 台本の動画形式が Shorts の場合: `1080x1920`
- それ以外: `1920x1080`

## 現在の制限

- 立ち絵は静止PNG/PSD抽出キャッシュを使います。
- 口パクは時間周期ベースの簡易実装です。WAV音量解析は未実装です。
- まばたきは周期ベースです。ランダム化は未実装です。
- 感情タグに応じた表情差分は未実装です。
- 背景切り替えは音声ファイル名の先頭番号に依存します。
- YMM4の細かいタイムライン、テロップ演出、立ち絵位置、表情制御は再現していません。
- `run_pipeline()` 経由の `YMMなし生成(test)` でも、現段階では `.ymmp` は保存されます。
- 中間フォルダ `_native_test/` は残ります。

## 段階別ロードマップ

### 第一段階: ffmpeg簡易MP4出力

状態: 実装済み

目的:

- YMM4を起動しなくても、既存素材からMP4を得られることを確認する。
- 台本貼り付けからの生成導線と、既存履歴からの単体MP4化導線を用意する。

実装済み:

- `YMMなし生成(test)` ボタン
- `YMMなしMP4化(test)` ボタン
- `core/native_renderer.py`
- 背景画像の動画化
- 音声WAV結合
- BGM合成
- ASS字幕焼き込み
- ずんだもん/めたんの字幕色分け
- ffmpegパスを `FFMPEG_BIN` で変更可能化

この段階の品質目標:

- 動画として再生できる
- 音声が最後まで入る
- 字幕が概ね音声と同期する
- アップロード候補のMP4として扱える

まだやらない:

- 立ち絵
- 口パク
- まばたき
- YMM4同等の演出再現

### 第二段階: 静止立ち絵の合成

状態: 実装済み

目的:

- 背景の上にずんだもん/めたんの立ち絵を表示し、最低限の解説動画らしい画面にする。

実装済み:

- `assets/characters/zundamon.png`
- `assets/characters/metan.png`
- ffmpeg filter_complex による静止立ち絵オーバーレイ
- Shorts/Longで立ち絵サイズを切り替え
- `NATIVE_RENDER_CHARACTERS` でON/OFF可能
- `NATIVE_CHARACTER_HEIGHT_SHORTS` / `NATIVE_CHARACTER_HEIGHT_LONG` でサイズ変更可能

現在の配置:

```text
ずんだもん: 左下
めたん: 右下
字幕: 立ち絵より上の描画レイヤー
```

この段階の品質目標:

- ずんだもん/めたんが常時表示される
- Shortsでも字幕と立ち絵がぶつからない
- 既存の背景+字幕+BGM出力を壊さない

残課題:

- PSDから差分PNGを書き出すルールは未確定
- 話者に応じた前面/強調表示は未実装
- 表情差分は第三段階で扱う

### 第三段階: 口パク・まばたき先行実装

状態: 実装済み

目的:

- PSDから口・目の差分PNGを生成し、話しているキャラだけ口パクさせる。
- 一定間隔で目閉じ差分を重ねてまばたきさせる。

実装済み:

- `core/native_character_assets.py`
- PSD自動探索
- PSDから `base` / `mouth_closed` / `mouth_half` / `mouth_open` / `eye_closed` をキャッシュ生成
- 話者判定に応じて、話しているキャラだけ口差分を短周期でオーバーレイ
- ずんだもん/めたんの目閉じ差分を周期をずらしてオーバーレイ
- `NATIVE_ENABLE_LIPSYNC` / `NATIVE_ENABLE_BLINK` でON/OFF可能

この段階の品質目標:

- 話しているキャラだけ口が動く
- 話していないキャラは口パクしない
- まばたきが自然な頻度で入る
- 素材抽出に失敗した場合は静止立ち絵にフォールバックする

残課題:

- WAV音量解析による自然な口開閉は未実装
- 現状は時間周期ベースの簡易口パク
- 感情タグに応じた表情変更は未実装

### 第四段階: 表情差分・話者状態

状態: 未実装

目的:

- 台本の話者・感情タグに応じて表情差分を切り替える。

想定作業:

- `ScriptParser` の dialogue item から `character` と `emotion` を読む
- `ノーマル`、`あまあま`、`ツンツン` などの感情を素材名へマッピングする
- 話しているキャラを少し強調する
- 話していないキャラはニュートラル表情に戻す

推奨ファイル:

```text
core/native_character_assets.py
```

この段階の品質目標:

- セリフごとに表情が変わる
- 話者が視覚的に分かる
- 素材が足りない表情は安全にノーマルへフォールバックする

### 第五段階: 音量ベース口パク・微動

状態: 未実装

目的:

- 現在の周期ベース口パクを、WAV音量に合わせた口パクへ改善する。
- 静止感を減らし、YMM4に近いキャラ表示にする。

想定作業:

- WAVを短い窓幅でRMS解析する
- 音量を `closed` / `half` / `open` に分類する
- まばたき間隔をランダム化する
- 軽い上下揺れ、話者切り替え時の微小移動を追加する

この段階の品質目標:

- キャラが完全な静止画に見えない
- まばたきが多すぎず自然
- 口パクと競合しない

### 第六段階: YMM4依存の分離

状態: 未実装

目的:

- `run_pipeline()` からYMM4プロジェクト保存を切り離し、本当にYMM4なし生成として短時間化する。

想定作業:

- 素材生成処理とYMM4タイムライン構築処理を分離する
- `run_pipeline(..., save_ymmp=False)` のようなフラグを検討する
- YMM4なし生成時は `.ymmp` 保存をスキップする
- 既存の通常生成は今まで通り動くことを維持する

この段階の品質目標:

- YMMなし生成でYMM4プロジェクト作成時間を削減する
- 通常生成の互換性を壊さない
- アップロードフローは生成されたMP4をそのまま扱える

## 今後の拡張候補

### 1. 立ち絵表示

PSDから差分PNGを書き出し、以下のような構成にする想定です。

```text
assets/characters/zundamon/
  base.png
  eyes_open.png
  eyes_closed.png
  mouth_closed.png
  mouth_half.png
  mouth_open.png

assets/characters/metan/
  base.png
  eyes_open.png
  eyes_closed.png
  mouth_closed.png
  mouth_half.png
  mouth_open.png
```

最初は静止立ち絵をPillowで背景に重ねるのが安全です。

### 2. 口パク

WAVのRMS音量から以下のように差分を切り替えます。

- 無音に近い: `mouth_closed`
- 中くらい: `mouth_half`
- 大きい: `mouth_open`

### 3. まばたき

3-7秒間隔のランダムイベントで、2-4フレームだけ `eyes_closed` に切り替えます。

### 4. 完全なYMM4非依存化

現在の `run_pipeline()` はYMM4プロジェクト作成まで含んでいます。最終的にYMM4依存を薄くするなら、素材生成とタイムライン保存を分離し、YMM4プロジェクト保存をスキップできるフラグを追加するのがよいです。

候補:

```python
run_pipeline(..., save_ymmp=True)
```

または素材生成専用関数へ分割:

```python
generate_assets(...)
build_ymmp_project(...)
render_native_test(...)
```

## 動作確認

確認済み:

```powershell
.\.venv\Scripts\python.exe -m py_compile gui.py core\native_renderer.py config.py
.\.venv\Scripts\python.exe -m unittest tests.test_upload_scheduler tests.test_upload_records
```

既存のアップロード済み履歴を使って `render_native_test()` のMP4生成も確認済みです。
