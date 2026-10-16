# タイムラインと動画レンダー

WP-R2-7 の描画境界は `picocast_media::render` が所有する。`TimelineRenderer` にチャンネル、混音済み `AudioOutput`、背景、準備済みキャラクター、実測済み字幕、設定、外部ソフトの絶対パス、新しい出力ディレクトリを明示して渡す。実設定・実 DB・現在チャンネルを内部で探さない。

## 時刻と素材

`RenderTimeline` のミリ秒区間は開始を含み終了を含まない。背景は先頭から末尾まで隙間・重複なく覆い、キャラクターと各字幕トラックは順序と範囲を検査する。同じ場所・時刻で重なる字幕トラックは拒否する。背景は画像取得側が所有確認した `RenderBackground { channel_id, source_id, image }`、キャラクターは R1 の CAS と画素検査を通した `PreparedCharacter` を受ける。背景にも画素の SHA256 と寸法を来歴として残す。

`FrameRate` の有理数からフレーム時刻を計算し、必要フレーム数は切り上げる。ffprobe の有理数が約分されても数値として照合する。混音のチャンネル・尺を確認し、音声ファイルは共通 `paths::require_regular_file` で通常ファイルだけを受ける。キャラクターへはセグメント内の時刻と発話・表情・音素・動き設定を明示する。表情使用中の口・目の無効化はキャラクター所有者の契約をそのまま使う。

背景はアスペクト比を保つ cover 配置、1 以上の開始/終了ズーム、0〜1 の開始/終了パンで指定する。新しい背景の先頭区間を、前の背景の終端画素からクロスフェードできる。透明画像は明示した不透明背景色へ合成する。リサイズはキャラクターと共通の premultiplied alpha + Lanczos3、重ね合わせも共通 source-over を使う。品質を落とす別アルゴリズムへの自動切替は行わない。

## 字幕を測定したフォントで描く

`SubtitleLayout` はフォント集合・文字スタイル・領域寸法を保持する。`TextLayoutEngine::rasterize_cue` は測定と同じ `FontSystem` と `shape_runs` を使い、cosmic-text/swash で実画素を生成する。ffmpeg の drawtext や別のフォント探索へ文字列を渡さない。強調ごとの色・weight、実測時の原点、左右/中央揃え、注入したフチ色と幅を使用する。欠損 glyph、別フォント集合、実画素のはみ出しは停止する。

`SubtitleRasterOptions` は字幕とサムネイルから共用できる serde 型で、揃え・フチ色・画素数・フチカーネル検査上限を保持する。字幕の表示区間だけ完成フレームへ合成する。通常出力のラスタライズ結果は原寸を保持し、明示 preview だけ測定済み画像を比率どおりに縮小する。

## 設定・GPU・外部プロセス

`RenderOptions` に原寸、`Final` または `Preview { size }`、fps、画素/フレーム/尺/作業メモリ上限、入力キュー長、尺許容差、CPU thread 数、AAC bitrate、エンコーダ候補順、外部プロセス時間/出力上限、期待する版を注入する。preview は原寸以下かつ同じアスペクト比だけを許可し、失敗時に解像度を黙って下げない。呼出側が所有する復号済み素材とキャラクターキャッシュはそれぞれの素材側予算で管理し、renderer は字幕キャッシュ・待機フレーム・RGBA32F リサイズ中間・背景のクロスフェードを確保前に検査する。

`ffmpeg -encoders` と候補順から `libx264` / `h264_nvenc` を選ぶ。NVENC には同じチャンネルの共通 `GpuPermit` が必須で、permit の device index を `-gpu` へ渡す。permit なし・未搭載候補を除いた理由はレポートへ残す。CPU を使ってよいかも候補順に明示する。選んだエンコーダの実行失敗後に別経路へ自動再試行しない。追加の HEVC/AV1/AMF/QSV/VideoToolbox は未実装。

フレームは有限長の bounded キューから共通 `proc::run_with_input` へ RGBA として流す。フレーム列の巨大な中間ファイルは作らない。プロセス・timeout・入力失敗・kill/reap は共通 proc が所有し、キャンセルと producer 失敗はその scope を終了する。字幕描画の準備や 1 フレーム内の CPU 処理は同期処理で、キャンセルは次の境界で検出する。

ffmpeg と ffprobe の版の先頭行を毎回記録し、期待版との相違を `version_warnings` に明示する。映像は H.264/yuv420p、音声は AAC。完成後に ffprobe で映像/音声各 1 stream、codec、寸法、フレーム数、fps、尺を検査する。`render.json` はチャンネル・job・UTC時刻・版・選定理由・原寸/出力寸法・字幕のフォント集合と表示区間・検査結果を持つ。

## 公開と失敗

一時出力は最終先と同じ親のランダム stage に隔離する。検査後に共通 `fsutil::publish_new_directory` で新しいディレクトリへ原子的に公開する。既存先は空でも置換しない。返す `video.mp4` / `render.json` の名前は renderer 内の定数が正本。途中失敗は stage の所有 scope で削除し、最終先を作らない。呼出側は最終先の親を用意し、出力先の管理名を正本から渡す。

停止コードは `E-RENDER-SETTINGS` / `TIMELINE` / `ASSET` / `OUTPUT` / `VERSION` / `ENCODER` / `ENCODE` / `VERIFY` / `CANCELLED` と `E-SUBTITLE-RASTER`。共通ファイル・プロセス・キャラクターの失敗は元の `AppError` を上位へ伝える。描画の失敗工程とチャンネル/job は tracing へ記録し、利用者向けに内部トレースを含めない。

## 限定検証と未受入

```powershell
cargo test --locked -p picocast-media render::tests
cargo test --locked -p picocast-media character::tests
cargo clippy --locked -p picocast-media --all-targets -- -D warnings
$env:PICOCAST_TEST_FFMPEG = (Get-Command ffmpeg).Source
cargo test --locked -p picocast-media render::tests::installed_cpu -- --ignored --nocapture
```

通常の限定 3 テストは録画 process を通し、128×72 / 10fps / 0.6 秒の 6 フレーム、実 Yu Gothic で描いた字幕の 200〜400ms だけの表示、CPU候補と permit 不在、別チャンネル、背景の隙間・クロスフェード、fps の約分、設定の桁あふれ、既存先不変、検査失敗/事前キャンセル時の公開なしを確認する。共有合成を使う旧 Pillow 画素一致を含むキャラクター 5 テストも成功した。

Windows の導入済み ffmpeg/ffprobe 8.0.1 で明示 CPU fixture 1 件を実行し成功した。合成 PCM と背景・実 Yu Gothic 字幕だけを使い、libx264 から出した MP4 を再復号して 6 フレーム、字幕が正確に 2 フレームだけにあること、音声が無音ではないこと、ffprobe の寸法・codec・尺を確認した。実素材・実 DB・サービス・GPU は変更していない。

旧版と同じ実台本の尺 ±0.1 秒/字幕数/全表示区間の比較、60 秒 Shorts preview の 10 秒以内という性能条件、実素材の見た目、長時間の速度とメモリ、NVENC の実機、GPU と画像生成の同時利用、macOS は未受入。上記の小さい合成 fixture を、これらの完了証拠として扱わない。
