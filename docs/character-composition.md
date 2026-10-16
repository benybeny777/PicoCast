# キャラクターのレイヤー合成

`picocast_media::character` は、R1 で登録したチャンネル内の CAS レイヤー PNG を読み、表情・音素に合う口・まばたき・話者の軽い動きを合成する。PSD を実行時に開かず、Python・外部サービス・素材取得も使わない。描画は同期処理で、長い動画のフレーム生成を UI スレッドへ直接載せない。

PNG の処理には `image 0.25.10` を使う。[公式 Cargo.toml](https://github.com/image-rs/image/blob/v0.25.10/Cargo.toml) は MSRV Rust 1.88.0、MIT OR Apache-2.0 を指定する。プロジェクトの Rust 1.95 と適合する。この機能の入力は登録済み RGBA8 PNG だけで、他の形式やビット深度へ無言変換しない。

## 登録データと所有境界

`CharacterLayers::load` へ `Store`、`ChannelId`、キャラクター ID、CAS ルートの絶対パス、`CharacterLimits` を指定する。

1. typed repository で対象チャンネル内の `Character` と `AssetRef` を確認する。
2. `layer_manifest_sha256` と `psd:manifest`、各 `psd:layers/...png` / `psd:variants/...png` の所有関係を照合する。
3. `fsutil::content_asset_path` で実体を引き、ルート外参照・シンボリックリンク・サイズ・拡張子・SHA-256 の不一致を拒否する。
4. R1 の `character_layers::validate_manifest` で資格・対応合成モード・階層・全 variant を検証する。検証規則を描画側に複製しない。
5. PNG の寸法・RGBA8 を検査し、ファイル容量・画素数・レイヤー数・variant 数・復号メモリの上限を適用する。
6. 各 variant のレイヤーを再合成し、登録された旧版の基準 PNG と比較する。manifest に記録された画素許容差を超えれば停止する。

実データへの新規登録・参照の変更は行わない。未登録の画像ファイルや別チャンネルのキャラクターを、直接のパス指定で描画へ混ぜる入口は持たない。

## レイヤーと表情

合成順は manifest のレイヤー順を維持する。親グループの非表示も子へ適用する。R1 で資格を確認した normal / pass-through のレイヤーだけを扱い、未対応のブレンドやクリッピングを別の描き方へ降格しない。元 PNG に含まれる不透明度をもう一度掛けない。

RGBA8 の source-over と整数丸めは、旧 Python の `tools/export_psd_layers.py::compose_layers` が使う [Pillow の合成](https://github.com/python-pillow/Pillow/blob/12.2.0/src/libImaging/AlphaComposite.c) と揃える。透明画素の RGB も含めて fixture で一致を確認する。

`CharacterBinding` に閉口時の base、半開き・開口・閉眼の variant ID、表情名から variant ID への対応、口とまばたきの有効状態を明示する。必要な variant が無い場合は停止する。

`prepare` は base からの可視状態の変更を使い、口 3 状態 × まばたき 2 状態と指定表情を事前合成する。以降のフレームはこの画像を再利用し、大量の元レイヤーを毎回読み直さない。事前合成のメモリも上限に含め、準備後に元レイヤーのバッファを解放する。

**表情 PNG を指定したフレームでは、その区間の口・目の追加変更を必ず両方 0 にする。** 表情自身が含む口・目だけを描き、`mouth_layer_changes=0`、`blink_layer_changes=0`、`blinking=false` を返す。上位層は区間の表情指定を全フレームへ一貫して渡す。存在しない表情を通常表情へ切り替えることはない。

旧版のぼかした差分 PNG を新たに推測生成する経路は持たず、登録済みの元レイヤーの可視状態から口と目を組み合わせる。実 PSD の合成品質は、R1 の書き出し資格と実素材受入の両方で確認する。

## 音素から口の時刻へ

`PhonemeTimeline::from_synthesis` は `picocast_voice::SynthesisResult` のチャンネル、実合成 query、検証済み WAV の尺と末尾無音を読む。録画用には `from_query` を使う。

時刻は [VOICEVOX ENGINE 0.25.2 の公式処理](https://github.com/VOICEVOX/voicevox_engine/blob/0.25.2/voicevox_engine/tts_pipeline/tts_engine.py) に対応する。調整値は `PhonemeTimingPolicy` から注入する。

- 前後無音・子音長・母音長・句読点の休止を順に並べる。
- query の速度・休止長・休止倍率を反映する。旧 query に休止倍率フィールドが無い場合の値も明示注入する。
- 有効にした疑問語尾上昇は、末尾有声モーラの追加母音長を含める。
- 音素ごとにデコーダーのフレーム数へ変換し、偶数丸めする。現在のエンジンでは注入値 24,000 samples/sec ÷ 256 samples/frame = 93.75 frames/sec。
- `voice` が補った末尾無音も閉口とする。検証済みの無音を持たない単なる query/尺では、大きな尺の不一致を認めない。

`FrameRate` は分子・分母を指定でき、各動画フレームの時刻で音素を選ぶ。音素名から `Closed` / `Half` / `Open` への対応表も呼出側が明示する。未知の音素を勝手な口へ割り当てない。非話者と音声区間外は閉口する。

## 動きと配置

`CharacterMotion` にまばたきの区間、非話者のまばたき可否、話者の揺れの振幅・周波数、登場時の倍率変化と長さを指定する。乱数・現在時刻・キャラクター名の特例には依存しない。揺れと登場時の動きは話者だけに適用する。

`frame` の結果は元解像度の画像、移動量、倍率を分けて返す。`place_character` は明示された位置と倍率で画面へ重ねる。等倍では再サンプリングせず、必要な拡大縮小は前乗算アルファの float 画像に Lanczos3 を適用して透明縁の色漏れを防ぐ。中間バッファもメモリ上限へ含める。画面外の切り取りは `allow_clipping=true` の明示指定が必要で、座標の桁あふれは常に拒否する。

PNG 保存は `CharacterFrame::save_new_png` → `fsutil::atomic_write_new` を使う。既存先を上書きしない。保存先の親ディレクトリは上位の工程管理で用意する。

停止コードは `E-CHARACTER-CONFIG` / `ASSET` / `CHANNEL` / `PIXELS` / `RIG` / `TIMING`。安定した対処手順付きの `AppError` と `tracing` を使い、内部スタックを利用者向け出力へ埋め込まない。

## 限定検証と未受入

```powershell
cargo test --locked -p picocast-media character --lib
cargo clippy --locked -p picocast-media --all-targets -- -D warnings
```

専用 fixture は合成した小さい RGBA だけを旧 `compose_layers` へ渡して採取したもので、実 PSD・個人素材を含まない。通常・半開き・開口・閉眼・半開きと閉眼・表情の画素を記録する。

限定 5 テストで、R1 登録から CAS 読取までを一時 DB で通し、半透明と親グループの非表示を含む旧版画素一致、表情時の口/目変更 0、音素境界から ±1 動画フレーム以内の口の切替、疑問語尾、偶数丸め、追加末尾無音、他チャンネル拒否、ハッシュ破損、未対応ブレンド、基準から 1 画素のずれ、既存保存先、座標の桁あふれ、透明縁の色漏れを確認した。

実PSD2種の書き出しを許容差0で受入検査したところ、ずんだもん113レイヤー/11variant/最大差25、めたん79レイヤー/11variant/最大差13で両方不合格となった。Display P3の元色空間で階層float32合成後にRGBA8化・ICC変換する旧版と、各レイヤーを先にRGBA8化・ICC変換してPillow互換で合成する現在の形式は同値ではない。めたんの非表示口差分 `6/4` は未対応MULTIPLYでもある。Rust登録口は不適格manifestを拒否するため、これらを適格素材として取り込まない。原因・限定probe・再現fixtureの証拠は [PSD書き出し](psd-layer-export.md#実psdの受入不合格と原因2026-10-16) に記録した。

許容差・基準PNGを変更せず、元PSD・実DBを保持した。全色LUTやpresetだけを使う別方式も追加していない。実PSDの忠実なレイヤー合成、実登録済みキャラクターの見た目、実音声を再生した口との同期、長時間動画での速度・メモリ、macOS は未受入。現在のPillow互換検査を、それらの実確認が済んだ証拠として扱わない。
