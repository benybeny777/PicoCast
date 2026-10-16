# 台本エンジン（WP-R2-2）

`picocast-script` は台本の取り込み、DB版テンプレートの組み立て、構造化生成、原子的な保存を担当する。生成は `generation::generate_and_save` から共通 `picocast-ai::Gateway` を呼ぶ。独自記法は互換取り込み・書き出し専用で、LLM生成結果を記法解析して救済しない。

## 型と検証

`document::StructuredScript` は `project` と `scenes` を必須にし、各SceneがLineを持つ。未知フィールド、必須キー欠損（nullable項目も明示的なnullが必要）、空タイトル・背景・本文、重複IDを拒否する。IDは英数字・`_`・`-` に限る。話者IDは同じチャンネルの有効キャラクター、style_idはそのキャラクターの登録値だけを許す。

`Limits` の最大シーン数・総行数・本文文字数・pause上限は呼出側が設定から注入する。文字数はUnicode文字単位、Gatewayへの送信上限は別途UTF-8バイト数として検査する。台本のformatはshorts/longの列挙型である。

schema検査、serde検査、話者別style・総行数等の文脈検査はGatewayの同じ検査経路で行う。形式不正時の再生成は最大1回。台本側に独立した再試行ループを作らない。キャンセル後はProjectを保存しない。実送信で発生した費用の記録はDB保存の失敗時も取り消さない。

## テンプレートと掛け合い

チャンネルごとに `PromptTemplate.kind` のdefaultを1件要求し、その `PromptTemplateVersion` の最大版を読む。最大版が無効なら停止し、古い有効版に戻らない。テンプレート未登録、別チャンネル、未知のenvelopeも停止する。`legacy-template-v1.fields.is_enabled` は旧DBの整数0/1として検査する。`template-v1` は同じfields構造でboolを要求する。

キャラクターも `legacy-character-v1.fields.enabled`（整数0/1）または `character-rules-v1`（bool）の有効な行だけを使う。旧データのprofile_idは引数のChannelIdと一致しなければならない。役割・口調・禁止表現・掛け合い・style対応はDBの内容から組み立てる。

共通の説明密度・掛け合い規則は `src/dialogue_rules.txt` の `DIALOGUE_RULES` を正本とする。ずんだもんの具体的説明と、めたんの視聴者目線の疑問を優先し、復唱や機械的な交互会話を増やさない。後続QAも同じ定数を参照できる。

title/meetingの組み立てもDBの版を使う。横展開判定基準は `PromptContext.expansion_criteria` へ明示注入し、分析の閾値を台本側へ複製しない。Analytics未取得はその事実をプロンプトに明記する。これは「取得失敗を空で継続」する処理ではなく、呼出側が明示的に未取得として渡した場合だけである。title/meetingは台本生成用キャラクター未登録でも組み立てられる。

## 旧記法と原文の保護

`legacy::parse` / `write` は旧 `ScriptParser` の日本語・英語ラベル、背景番号、括弧付き感情・表情、メタの複数行、改行継続、旧版の右括弧補正を扱う。ラベルの別名と書出し名は一つの表で管理する。未知話者補正は `ParserOptions.unknown_character` を呼出側が明示した互換処理だけに限り、警告を記録する。通常はNoneで停止させる。

`compatibility::import_revision` はchannel importerが保存した `kind=legacy_metadata` の原文revisionを読み、新しい連続revisionへScene/Lineを保存する。元revisionは上書きせず、変換結果にも元snapshot・全解析Itemを来歴として保持する。専用列のないサムネイル指示・会議候補・アンケート等も消えない。背景なしの台本には `ImportOptions.initial_background` の明示指定が必要で、空の背景を捏造しない。感情からstyleへの登録対応がなければ停止する。

互換処理の既定format/title/pauseも `ImportOptions` から渡す。独自記法の書出しは全Itemを渡すことで元メタを保つ。旧パーサーの会議候補・投票表示等のUI補助関数はこのcrateの本番解析APIとは別であり、旧画面そのものの移植を完了したとは扱わない。

## DB保存の境界

`Store::save_project_revision` はImmediate取引でProject、追記専用ProjectRevision、Scene、Lineをまとめて保存する。新規はrevision=1、更新は現在版+1だけを受け付け、版競合、非連続ord、重複ID、別projectからのID流用、別channel、存在しないspeakerを拒否する。取引途中で外部参照が衝突したら全体を戻す。

生成前にも同じ版条件と保存先・言語を検査し、既に保存不能な要求でAI費用を使わない。検査後の同時更新まで予約するものではないため、保存時のImmediate取引でも版を再確認し、競合時は上書きせず停止する。

既存グラフは対象projectのものだけを読む。保持するIDの並べ替えは既存ordより上の一時領域を使い、UNIQUEを弱めない。消える行・シーンに音声等のAssetRefが残っていれば削除を止める。AssetRefや音声を保存処理が勝手に削除しない。既存の投稿状態・topic・予約・作成日時は台本更新で初期化しない。

AssetRefがあるLineの本文・話者・読み・accent・style・表情・強調・pauseの変更も、現段階では `E-STORE-IDENTITY` で止める。順序の入れ替えは許す。依存hashの無効化と必要素材の再生成が原子的に実装された時点で、この制約を明示的に解除する。古い音声参照を残したまま意味だけ変更して再利用しない。

使用したテンプレートID/版、構造化台本、Gateway来歴をrevisionに保存する。telopsや追加メタはこのsnapshotを正本に保持し、camera_jsonへ混ぜない。新規Projectは生成完了前には存在しないため、その生成のcost ledgerのproject_idはNoneとなる。既存Projectの再生成はproject_idを記録する。いずれもrequest hashは生成結果の来歴へ残す。

## 確認範囲

ローカルの合成fixtureだけで確認する。旧台本oracle 2ケースの構造・書出し後の再解析一致、複数行/補正、有効テンプレート、strict型、style、版競合、越境、取引rollback、素材参照維持、偽Gatewayの再生成とProject保存を検査する。

実API、実チャンネルDB、個人素材、実際の生成品質は未確認。画面操作、テンプレート編集UI・差分表示・戻す画面（WP-R4-9）、生成台本の内容採点（WP-R2-13）、実レンダーは後続WPの範囲である。GitHub Actionsは使用しない。
