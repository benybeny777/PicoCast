# 字幕の実測文字組み

`picocast_media::subtitle::TextLayoutEngine`は、描画やffmpeg起動から独立した共通文字組みである。字幕のほか、後続のサムネ・画面プレビューでも同じ領域・フォント・強調範囲を渡して再利用する。旧Pythonの文字数折り返しを本番の代替経路として呼ばない。

## 入出力

`TextLayoutEngine::new(font_sources, locale)`は、明示した絶対パスのフォントファイルだけをロードする。OS全体の暗黙探索・フォント取得・小さいフォントへの降格は行わない。`font_families()`でロード済みファミリー名を確認できる。

`layout(text, emphasis, start_ms, end_ms, options)`へ本文、強調するUTF-8バイト範囲、開始・終了時刻、`LayoutOptions`を渡す。結果の`SubtitleLayout`はcue一覧を返し、各cueは時刻と行を持つ。各行は元本文のバイト範囲、本文、実測幅・高さ、描画原点補正、色・weightを付けたrunを保持する。フォント資源はengineが所有し、破棄時に解放する。

調整値は型付き引数から全て注入する。画面幅・高さ、行数上限、行のgrapheme数上限・下限、入力と測定回数の上限、文節内部改行の許可、行頭・行末禁則集合、表示時間下限、最大読み速度、フォントファミリー・サイズ・行高・通常と強調のweight・色・輪郭幅を固定値で埋め込まない。1文字行を禁止するため、最小grapheme数は2以上を必須にする。

## 改行と測定

1. Unicode grapheme境界を列挙する。結合濁点・異体字セレクター・絵文字の連結をコードポイント単位で分割しない。強調範囲も同じ境界に限定し、重なりと範囲外指定を拒否する。
2. BudouX日本語モデルの文節境界を候補へ加える。Rust portの境界がchar位置であるためUTF-8バイト位置へ変換する。英語の空白も優先候補として扱う。
3. 各候補を`cosmic-text`のAdvanced shapingで実測する。太字を含むrich textとして測定し、glyph欠損を明示エラーにする。
4. shapingのadvanceに加え、同じフォント・weightの`skrifa` glyph outline boundsを測る。負のbearing、輪郭、ピクセル境界への外向き丸めを領域に含める。行高を超えるglyphを小さいフォントへ置き換えない。
5. 禁則・最小文字数・幅・行高を満たす候補から、動的計画法で文節内改行数、行数、余白の偏りの順に小さい配置を選ぶ。文節内改行を許可した場合は結果の`inside_phrase_break`へ残す。
6. 行数・高さ上限でcueを分割する。各cueの表示下限と読み速度から必要時間を計算し、元の開始・終了範囲内へ単調に割り当てる。時間不足では勝手に字幕を省略したり他cueと重ねたりせず停止する。

改行を挿入しても元本文と強調を保存する。入力の明示改行は段落境界として維持する。空段落、1graphemeしかない段落、禁則に反するしかない入力、単一glyphも入らない幅、測定上限到達、表示時間不足は成功扱いにしない。

成功結果に対して、幅・高さ超過、1文字行、注入した禁則集合への違反を認めない。設定された禁則集合そのものの規格適合は設定正本とQA側で管理する。font fileの更新により実測結果は変わるため、同じファイルを後続描画でも使用する。

エラーは`E-SUBTITLE-SETTINGS`（設定）、`FONT`（未導入・欠損glyph・計測不能）、`INPUT`（本文・強調範囲）、`LIMIT`（入力・計測量）、`LAYOUT`（配置不能）、`TIME`（時間不足）で区別し、安定コードと対処を返す。本文や内部トレースをエラーへ含めない。

## 依存と検証

2026-10-16に一次資料とcrate metadataを照合した。

| 依存 | 版 | MSRV | ライセンス・採用範囲 |
|---|---|---|---|
| [cosmic-text](https://docs.rs/cosmic-text/0.19.0/cosmic_text/) | 0.19.0 | 1.89 | MITまたはApache-2.0。既定feature無効、stdだけを有効化しfontconfig依存を避ける |
| [budouy](https://docs.rs/budouy/0.2.2/budouy/) | 0.2.2 | 1.88 | Apache-2.0。stdとvendored-modelsだけを有効化 |
| [unicode-segmentation](https://docs.rs/unicode-segmentation/1.13.3/unicode_segmentation/) | 1.13.3 | 1.85 | MITまたはApache-2.0。grapheme境界 |
| [proptest](https://docs.rs/proptest/1.12.0/proptest/) | 1.12.0 | 1.88 | MITまたはApache-2.0。開発依存、stdだけを有効化 |

BudouX本家の公式言語提供はPython・JavaScript・Javaであり、`budouy`は[Google BudouX](https://github.com/google/budoux)の第三者Rust portである。旧`budoux` crate 0.1.1はMSRVが宣言されていないため採用しなかった。

Windowsで`cargo test -p picocast-media subtitle --lib -- --nocapture`を実行し、既存OSのYu Gothic regular/bold・Segoe UI Emojiを明示ロードして日本語、英語、句読点、絵文字、強調、極小幅、短すぎる時間を確認する。property testは固定seedで48入力を生成し、成功を必須にした配置で幅・高さ・grapheme・禁則・時刻・文字保持を検査する。フォントのダウンロードや同梱は行わない。

280px領域の実測fixtureでは、日本語行の最大幅279.637px、英語239.811px、絵文字混在279.637pxを確認した。これは当該OSフォントでの測定結果であり、全環境共通のgolden幅に固定しない。実フォント測定fixtureはWindowsに限定している。macOS等では指定した現地フォントでの追加受入が必要である。

実動画への合成、画面での視認性、色付き絵文字の実描画、ffmpegの最終字幕レンダラーとの差分、サムネ・UIの接続は後続WPで検証する。このWPは実測の文字組み・時間割当までを扱う。
