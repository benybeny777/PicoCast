# 作業指針（共通）

- 利用者の依頼、会話、プロジェクトの現状から目的と作業範囲を判断し、必要な修正・検証・引き継ぎまで完了する。
- 日常的で取り消せる判断は自律的に進める。結果が大きく変わる判断や新しい権限が必要な場合だけ、許可済みの準備を終えてから確認する。
- 利用者の明示指示を優先し、読み取り専用・編集・テスト・公開・マージ・削除の境界を守る。途中の修正指示は直ちに反映する。
- 指示やスキルが停止・確認を要求する場合は、対象ファイルと該当規則を具体的に説明する。
- 結果を先に、根拠と未確認事項を短い日本語で伝える。比較や手順に必要な場合だけ表や箇条書きを使う。
- 独立した範囲で並行作業が可能かつ許可される場合は子エージェントへ委任し、目的・対象・根拠・報告形式を指定する。統合と最終判断は主担当が行う。
- 変更の影響に合う検証を行い、同じ確認の繰り返しや実装の言い換えだけのテストを増やさない。追加検証は新しい変更・失敗・未解決の懸念がある場合に限る。

出典: https://developers.openai.com/api/docs/guides/latest-model#prompting-best-practices

# AGENTS.md — Claude Code / AI エージェント向け作業ガイド（ルール正本）

このファイルが唯一のルール正本です。`CLAUDE.md` はこのファイルへのリダイレクトのみです。ルールを追加・変更する場合はこのファイルだけを編集してください。

## 最重要運用ルール

- `AGENTS.md` はすべて日本語で記述する。英語セクション・英語コメントは追加しない。既存の英語記述を見つけたら日本語に置き換える。
- ルールに反する記述・命名・コメント・dead codeを発見した場合は、その場で修正して作業完了後に事後報告する。都度確認を求めない。
- ルール正本は `AGENTS.md` 1本。`CLAUDE.md` はリダイレクトのみなので編集しない。恒久ルールはすべてこのファイルに追記する。
- **ドキュメントは常に最新を保つ。コード・スクリプト・設定・依存関係・フォルダ構成など、README や SPEC.md に記載のある内容を変更したら、必ず同じ作業内でドキュメントも更新してコミットする。ユーザーから指摘されてから直すのは禁止。**
- 対象ドキュメントの目安: 仕様・画面・プロンプト・設定・生成フロー → `SPEC.md`、大きな変更 → `CHANGELOG.md`、起動手順・セットアップ・スクリプト名・APIキー・依存関係 → `README.md`。
- ドキュメント更新が本当に不要な軽微修正の場合のみ、不要と判断した理由を作業完了時に明記する。
- コミットメッセージ・ソースコードのコメントは基本的に日本語で書く（コミットは英語だけの件名にしない）。`feat` / `fix` / `docs` / `chore` などの短い英語プレフィックスや、API / JSON / config / 識別子・関数名など日本人にも通じる技術用語の英語はそのまま使ってよい（無理に和訳しない）。
- 運用や品質に影響する大きめの変更は `CHANGELOG.md` に残す。
- PowerShellで日本語ファイルを確認するときは、文字化けを避けるためUTF-8を明示する。`$OutputEncoding=[Text.UTF8Encoding]::new($false); Get-Content -Encoding UTF8 ...`、`$env:PYTHONIOENCODING='utf-8'; python -c "... Path(...).read_text(encoding='utf-8') ..."`（Windowsは `py -3`）、`rg`、`git diff` を優先する。
- PowerShell表示が文字化けしても、すぐにソース破損と判断しない。UTF-8で読み直してから判断する。
- 常に Codex / Claude の利用クレジット消費を抑えて作業する。不要な長文出力、重複調査、過剰なファイル読み込み、不要な並列探索、同じ確認のやり直しを避ける。
- まず `rg`、差分確認、必要最小限のファイル読み取り、軽い単体テストで判断する。大きい調査が必要な場合も、読む範囲を絞り、分かったことを短くまとめる。
- ChatGPT API と Google API（Gemini / Nano Banana 画像生成など）は費用が発生するため、ユーザー指示または運用上の明確な必要がある場合だけ実行する。ローカルLLM・ローカル処理・YouTube API はコストが実質かからないため必要なら積極的に使ってよい。ただし同じ取得や更新を無意味に繰り返さない。
- 既に未コミット変更がある場合は、ユーザーまたは別エージェントの作業として扱い、勝手に巻き戻さない。コミット時は目的に関係する差分だけをステージする。
- ユーザーから特に「コミットしない」「プッシュしない」などの指示がない限り、作業完了時は関連差分をコミットし、リモートへプッシュする。作業開始時点で未コミット差分がある場合も、ユーザーまたは別エージェントの作業として尊重しつつ、今回の依頼対象に含まれる差分はコミットしてプッシュまで行う。
- 大規模改修・影響範囲が広い変更・破壊的変更を含む場合は、エージェントが判断して作業ブランチを作成し、push 後に PR として提出する。この場合、ユーザーの明示指示なしに PR をマージしない。
- ファイル編集は `Edit` ツール（Claude Code）または `apply_patch`（Codex）を使う。検索はまず `rg` / `rg --files` を使う。
- **エラーはすべてそのまま例外として上位に伝播させる。`except Exception: pass` / `except Exception: return default` のようなサイレントスキップ・無言フォールバック・無言デフォルト降格は禁止。** 失敗時は原因が分かるエラーとして即中止する。フォールバック処理はユーザーが明示的に許可した場合のみ実装し、その箇所に `# フォールバック許可: 理由` コメントを付ける。
- **エラーになり得る箇所では、失敗時に必ずデバッグログ（`logging` 経由、role別 `app_debug_*.log`）へ出力する。** 例外を捕捉する箇所・処理が失敗扱いで終わる箇所・許可されたフォールバックを通る箇所はすべて、`_logger.error()`（例外は `exc_info=` でスタックを残す）または `_logger.warning()` で原因・対象・コードを記録する。ユーザー向けの job ログ・画面表示だけに出して `logging` へ残さない経路を作らない。ジョブ実行など複数経路が合流する箇所では、各所に散らさず合流点（funnel）で一括出力する。秘密値はログに含めない（`_SecretRedactingFilter` 任せにせず値自体を出さない）。
- **ユーザー向けの処理ログ・job ログ・画面・APIレスポンスへスタックトレースを出すことを禁止する。** ユーザー向けには安定したエラーコード、何が失敗したか、対象、具体的な対処手順だけを簡潔に表示する。スタックトレースは `_logger.error(..., exc_info=True)` でデバッグログ（role別 `app_debug_*.log`）のみに残す。`traceback.format_exc()` や例外文字列へ連結したトレースを job ログへ書き込まない。
- ユーザー操作で表示される停止系エラーは `core/error_codes.py` の `ERROR_CATALOG` に安定した `E-...` コードと対処手順を追加し、可能な限り `AppError` または `format_error(..., with_fix=True)` / `format_image_error()` 経由で返す。新しい `RuntimeError` / `ValueError` をユーザー向け経路へ直接出す場合は、既存APIのバリデーションなどコード化しない理由を作業報告に明記する。
- `ERROR_CATALOG` に追加する全コードは、キー名と `ErrorDef.code` を一致させ、`remediation` を空にしない。既存コードの意味を後方互換なく変更しない。未知コードを増やすより、同じ原因カテゴリは既存コードへ寄せる。
- ファイルポインタ、ネットワーク接続、画像/動画オブジェクト、subprocess、ブラウザ/GUIハンドルなどのリソースは明示的に解放する。`with`、`close()`、`terminate()`、一時ファイル削除などを使い、長時間処理では不要な大きい参照を手放してメモリも解放する。
- 初期データ類は `config/SEED/` 配下へ集約する。製品版として配布するテンプレート・初期パックは `config/SEED/prompt_packs/product/` に置き、チャンネル固有の勝ちプロンプト・実績入りテンプレート・ユーザー固有データを混ぜない。
- プロンプトテンプレートは `data/settings.db` の `prompt_templates` テーブルを正本にする。
  - テンプレートは `profile_id` 単位で所有。別 profile のテンプレートは使用不可。
  - `template_kind`: `script` / `title` / `meeting` の3種。`(profile_id, template_kind)` 単位でデフォルト1件。
  - 初期データは起動時 `seed_all_profiles()` が seed 用テンプレートファイルから投入する。製品版初期データは `config/SEED/prompt_packs/product/{seed_profile}/`、既存チャンネル互換データは `config/prompt_profiles/genres/{genre_profile}/` を使う。
  - 実行時のプロンプト組み立ては `core/script_prompts.py` が DB テンプレートから直接行う（ファイル読み込みなし）。
  - テンプレートが DB に未登録なら RuntimeError（フォールバックなし）。
  - 編集は設定画面「テンプレート」タブ または `POST /api/prompt-templates` で行う。
- `config/SEED/prompt_packs/product/{seed_profile}/` は製品版初期データ置き場。`/setup` のジャンル選択にはここだけを表示する。
- `config/prompt_profiles/genres/{genre_profile}/` は既存チャンネル互換のテンプレート seed 用ファイル置き場（`prompt_profile_loader.py` 経由）。実行時プロンプトでは参照しない。
- genre_profile が存在しない場合はエラー停止。別ジャンルへのフォールバックは禁止。
- 数値・座標・倍率・閾値・フラグなど「設定として変えうる値」はソースコードにハードコードしない。正本は `data/settings.db` と Web UI の設定画面に置き、`config/config.py` には既定値つき定数として集約する。新規設定で `.env` / `os.environ` を正本・保存先・通常の上書き手段として使うことは禁止する（プロセス起動用の一時フラグ、OSから渡される実行環境情報、`NVF_MASTER_KEY` は例外）。
- 新規の設定保存処理は `core.settings_store` / `web_app.services.config_service` 経由で DB に保存し、保存後は `setattr(cfg, key, value)` と必要モジュールへの伝搬で即時反映する。`os.environ[key] = value` で反映したことにしない。
- `config/config.py` の各定数には必ず末尾コメント（`# 説明`）を付ける。新規追加・変更時もコメントを省略しない。
- パス設定は、アプリ配下・同梱リソース・出力管理配下のものは原則として相対パスまたは `asset:` 参照で保存する。ただし VOICEVOX / AquesTalk / Stable Diffusion WebUI / ffmpeg / Ollama など外部アプリ本体・別ドライブ・ユーザーが任意に配置した外部ツールのパスは、移動追従より実体指定を優先するため絶対パスを許容する。外部アプリの絶対パスを無理に相対化しない。
- native立ち絵に表情PNG（`expression` 指定）を使用している場合、口パク・まばたきの差分オーバーレイを同セグメントで無効化する。表情PNGはPSDから合成した専用口・目レイヤーを含むため、base.pngとの差分オーバーレイと重ねると二重口・二重目が生じる。
- 台本・プロンプトを修正するときは、掛け合いの量より説明密度を優先する。ずんだもんが具体的な事実・理由・背景を説明し、四国めたんは説明役・補足役にせず、視聴者目線の疑問・違和感・説明の浅さを突く役にする。機械的な交互会話、相槌、復唱、情報が増えない押し問答を追加しない。
詳細仕様は [SPEC.md](SPEC.md) を参照。ここには作業上の注意点だけを書く。

## 進め方

- **進行中の作業への質問・指摘・部分的な了承は、中断指示ではない。** 状況は進捗メッセージで回答し、そのまま次の実作業へ戻る。「続けます」と言うだけで最終回答を送らない。最終回答前に残作業を点検し、依頼が完了した場合、利用者が停止を明示した場合、または利用者の判断・新しい権限が不可欠で安全に進められる作業が残っていない場合だけ区切る。
- **利用者が「読み取り専用」「編集禁止」と明示していない限り、「レビューして」は修正までの依頼である。** 指摘を並べて終わりにせず、見つけた問題はその作業内で直してテストまで済ませる。方針判断が要るものも妥当な既定を選び、採否・理由・代替案・検証境界を作業報告（PRがある場合はPR本文）へ書く。手順は `.agents/skills/review-yukkurijidou-changes/SKILL.md` を正本にする。
- **画面やログのエラー文を事実確認の代わりにしない。** 未導入・欠損・停止・権限不足などの表示を見ても、迂回・再導入・設定変更を提案または実行する前に、対象実体、DB・設定値、実行中プロセス、探索・分岐の順序を照合する。元の依頼を早く再開する目的で、原因修正より回避策を優先しない。
- **実装・配布・検証を簡単にする選択で、速度・画質・機能・対応機種・互換性・保守性のいずれかを犠牲にする場合は、採用前または判明した時点で利用者へ具体的に伝える。** 「安全」「簡単」だけを理由に欠点を隠さず、何がどの環境で劣るか、改善に何が要るか、今回実施するか保留するかを報告に残す。簡単な経路を実装しただけで、犠牲にした経路まで対応済みと扱わない。
- **実害のあるバグは見つけ次第その場で直す。** 別の作業中に見つけた場合も「今回の目的外」で保留にしない。実害とは、利用者のデータが消える・機能が黙って動かなくなる・誤った内容を見せる・費用や時間を無駄にさせる、のいずれか。目的が違うなら別コミット・別PRへ分けてよいが、分けることと後回しにすることは違う。すぐ直せない場合だけ、再現条件・影響範囲・着手条件を報告に残す。
- **大きなファイルは、肥大化を検知したら責務を棚卸しし、分割するか一体のまま保つかを先に判断する。** 行数だけを理由に分けない。唯一の正本、参照方向、公開する最小インターフェース、テストの境界を決め、その境界で保守・検証が独立する場合だけ分ける。読むファイル・共有状態・相互呼び出しが増える分割、単なる行移動、循環依存になる分割は禁止する。
- **コピペで類似コードを作ることを禁止する。共通化して最適化する。**
  - 対象: 既存コードを写して一部だけ変えた手順・判定・変換・定数表・正規表現・テンプレート部品・テストの組み立て、同じ不具合修正を別々の場所へ個別に当てること。
  - 責務の持ち主を1つに決めて共通化する。既存の共通層（`core/` の共通処理、`web_app/services/`、`web_app/security.py` など）に同じ責務があればそれを使い、持ち主が無い場合だけ新設する。違いは引数・設定・データ（表）で表し、呼び出し側に分岐を増やさない。
  - 既存の重複を見つけたら、特徴的な文字列・呼び出しの並び・定数で全体を検索して同型をすべて列挙し、同じ作業内で共通化する。
  - 責務・変更理由・所有者が違い、たまたま似ているだけのものは共通化しない。共通化しない判断をした場合は理由を報告に残す。
- **状態が壊れていたときに、空データで書き戻さない。** JSON・設定一覧・DB上のJSON文字列などを「読む → 直す → 書き戻す」処理で、読めなかったものを空として扱い次の保存で上書きすると利用者のデータが恒久的に消える。読めなければエラーを返して書き戻しを止めるか、破損元を退避してから扱う。

## 日本語で書く

- **利用者の目に触れるものはすべて日本語で書く。** 最終回答、作業途中の進捗メッセージ、確認の質問、ツール実行時に表示される説明文、コミットメッセージ、PR本文とPRコメント、コード内コメント、テスト名が対象。英語のまま残してよいのは、識別子・型名・コマンド・パス・設定キー・短いコミットプレフィックス・技術用語・外部の固有名詞と、ログやエラーの原文引用だけ。
- 途中で英語を書いたことに気付いたら、指摘を待たずにその場で日本語へ直して続ける。
- **日本語など非ASCII文字を含む `.ps1` はUTF-8 BOM付きで保存する。** Windows PowerShell 5.1 はBOMなしUTF-8を誤読するため。新規作成・編集した `.ps1` はBOMの有無を確認する。
- **容量は十進のMB／GBで書く。** 生のbyte数やMiB／GiBを利用者向け報告・PR本文へ単独表示しない。識別子・実装上のbyte列は対象外。

## ドキュメントの正本

- **現行仕様はコードではなくドキュメントを正本とする。** `SPEC.md`、`README.md`、`MANUAL.md`、`BUILD.md` の担当範囲に書かれた確定仕様とコードが食い違う場合は、原則としてコード側の不具合としてドキュメントへ合わせる。動いているコードを理由に不一致を追認しない。仕様変更が依頼の目的なら、ドキュメントを先に更新し、その仕様へコードとテストを合わせる。
- 正本ドキュメントに矛盾、実現不能、安全性・互換性・品質の悪化、明らかな誤記があると判断した場合は、黙ってコードへ適用したりコードを正として読み替えたりせず、該当箇所・問題になる条件・影響・推奨する訂正を利用者へ報告する。

## PR本文と引き継ぎ

- **PR本文には、別のエージェントが会話履歴なしで引き継げる改修設計を書く。** クレジットの枯渇、セッション切断、担当交代はいつでも起きる。「続きをやって」と言われた別AIが、PR本文だけを読んで同じ判断へ到達できるかを判定基準にして、次を含める。
  - **背景と原因**: 何が壊れていて、どの経路で起きるか。再現条件が要るものは条件も書く。
  - **設計判断と却下案**: 採った方式と、採らなかった方式とその理由。
  - **未完了の作業**: 終わらなかった部分、次にやること、着手条件。
  - **検証の状態**: 実行した検証と結果、この環境では確認できなかったこと（実機・GUI・外部サービス・資格情報が要るもの）を分けて書く。
  - **触ってはいけない前提**: その変更が依存している不変条件（工程順、DB正本、profile分離など）。
- 作業を途中で終える場合は、PR本文の冒頭へ「未完了。次にやること」を置き、Draftのままにする。ブランチと変更は必ずpushしてから終える。ローカルにしか無い作業は引き継げない。
- **CodexとClaudeは互いを自動起動しない。相互レビューは利用者の操作だけをトリガーとする。** CodexからClaude CLIを呼ぶことも、ClaudeからCodex CLIを呼ぶことも禁止する。利用者が対象成果物・レビュー担当・範囲を明示した場合だけ実行し、通常の実装・レビューは作業中のエージェント自身が完結させる。

## 後始末

- **一時ファイルは `dev/<作業名>/` の専用ディレクトリにまとめ、そのディレクトリを丸ごと削除すれば片付く構成にする。** スクリーンショット・変換途中のファイル・作業用スクリプト・一時ログを `dev/` 直下やルート、ソースディレクトリへ散らさない。専用ディレクトリ内に共有ファイル・モデル・`output/` へのリンクを作らない。後始末はエージェントが行い、実行基盤が削除を拒否した場合は未削除の対象と理由を報告する。
- **プロセスを止める前に、必ず親プロセスとコマンドラインで「自分が起動したもの」かを確かめる。** `python.exe` / `node.exe` / `ffmpeg` などは他アプリや利用者の作業も使っており、名前だけで一括終了すると稼働中アプリ（Web UI、`workers.runner`、VOICEVOX、SD WebUI など）を壊す。
- **子プロセスを起動したら、ハンドルを握っているだけで回収できると考えない。** ブラウザなど起動直後に本体を立て直す常駐物は、専用プロファイル・専用ディレクトリなど自分のものだと分かる起動経路で名指しして回収する。

## 依存の選び方

- **外部依存は原則として公式LTSまたは長期保守安定版を採用し、LTS相当が無ければ安定版latestを採用する。LLM・画像生成モデルはLTS扱いにせず公式の最新安定版へ追従する。** 互換性・ライセンス・対象OSの問題で旧版を維持する場合は理由と確認日を報告に残す。点検手順は `.agents/skills/audit-yukkurijidou-dependencies/SKILL.md` を正本にする。

## 作業スキル（`.agents/skills/`）

- 作業エージェント向けの再利用手順は `.agents/skills/<名前>/SKILL.md` を正本にする。Claude Code用の `.claude/skills/<名前>/SKILL.md` は同名の共通スキルを読むだけの薄い入口とし、手順・スクリプト・参照資料を複製しない。
- `.agents/skills/` と対応する `.claude/skills/` の入口はすべてGit管理対象にする。
- **同じ種類の作業が2回以上発生した、工程順を誤ると成果物が壊れる、混入・公開・破壊・課金の危険がある、または複数エージェントへ引き継ぐ作業は、その作業内で共通スキル化する。** 単発の小修正や一般知識だけの手順は無理にスキルへしない。
- 新規作成前に `.agents/skills/` を検索し、目的が重なるスキルがあれば新設せず既存スキルへ統合する。
- スキルを使うたびに、記載されたパス・コマンド・成果物を現行コード・文書と照合する。古い情報や不足分を見つけたら、そのスキルを同じ作業で更新してから続ける。
- `AGENTS.md` に恒久ルールではなく特定作業の工程・コマンド一覧が増えていて、スキルへ分離した方がよい箇所を見つけたら、対象と分離先候補を利用者へ報告する。
- スキル名は英小文字・数字・ハイフンだけの動詞始まりとし、`SKILL.md` のfrontmatterは `name` と「何をするか・どの依頼で使うか」を含む `description` だけにする。本文は日本語・命令形・500行未満を目安とし、一般論や作業日記を入れない。

## チャンネルプロファイル・DB正本

- 複数チャンネル・ジャンルは `data/settings.db:channel_profiles` で管理する。`is_active=1` が active profile。
- `profile_id` / `genre_profile` / `output_root` はチャンネルハンドルから `@` を除いた値に統一する。既存値が違う場合は関連テーブル・prompt seed フォルダ・output フォルダも移行する。
- 動画生成・履歴・画像確認・再レンダー・アップロード候補・Analytics・固定コメント・スケジュール・再生リストは active profile の `output_root` 配下だけを参照する。
- 特定チャンネル名・ハンドル・URLをコードにハードコードしない。未設定時に特定チャンネルへフォールバックしない。
- `require_active_profile()` は未設定なら例外。`get_active_profile()` は未設定時のみ None。food_trivia や default へのフォールバックを書かない。
- 別 profile の `output_root` へのアクセスは `web_app/security.py:safe_output_path()` が 403 で拒否する。
- APIキー（`google_api_key` / `openai_api_key` / `hf_token`）・YouTube client_secrets・OAuth token（`youtube_upload_token` / `youtube_analytics_token`）は profile_id 単位で `encrypted_secrets` に保存する。
- BGM は `data/settings.db:bgm_assets` で profile_id 単位に管理する。生成・再レンダー時は `profile_default` / `selected` / `none` の明示指定を使う。
- よみがな辞書は全チャンネル共通（プロファイル非依存）。`data/settings.db` の `reading_dictionary_entries` / `reading_candidates` が正本で、JSON ファイルや `output/{profile_id}/` 配下へ戻さない。

## Web UI 作業時の注意点

- Web UI は `127.0.0.1` のみバインドする。外部公開・認証なし運用は禁止。
- 認証情報（APIキー・OAuthトークン・client_secrets）は DB の `encrypted_secrets` テーブルに AES-GCM で暗号化保存する。`.env` / `client_secrets.json` / `token.json` / `token_analytics.json` は正本として使用しない。
- 認証情報の読み取りは `core.secret_store.load_secret()` / `has_secret()` を使う。`os.environ.get("GOOGLE_API_KEY")` など直接参照を新規に書いてはならない（`NVF_MASTER_KEY` のみ例外）。
- 認証情報の値をレスポンス・ログ・例外メッセージへ絶対に含めない。APIキー設定は bool（有無）のみ返す。
- DB 復号失敗・master key 取得失敗は例外を上位に伝播させる（フォールバック禁止）。
- OAuth refresh 後のトークンは `save_secret()` で DB へ再保存する。`token.json` / `token_analytics.json` を恒久ファイルとして新規作成しない。
- Web UI を唯一の操作入口とする。`workers/main.py` は生成パイプラインとしてのみ使う。
- 長時間処理はすべて `job_manager.py` でジョブ化する。HTTPリクエスト内で直接待たない。生成・レンダーは Web プロセスで実行せず、`metadata.db:jobs` に queued 登録して `workers.runner` が `profile_id` を固定して実行する。
- output/ 配下のファイルアクセスは `security.py: safe_output_path()` を必ず通す。
- 履歴フォルダ名（`history_name`）から実体パスを引くときは `security.py: find_history_dir()` に統一する（`videos/` → `000_uploaded/` の順で解決）。テーマフォルダは `output_root` 直下ではなく `videos/`・`000_uploaded/` 配下にあるため、`safe_output_path(history_name)`（base=`output_root`）で直接引かない。
- 台本本文の正本は `metadata.db` の `videos.script_content`。**`script.txt` ファイルは生成も参照もしない**。生成時は `save_script_content()` / `sync_folder_to_db(theme_dir, script_content=...)` で DB に保存し、台本を読む処理（再生成・レンダー・アップロード・表示・is_shorts・CTAカウント）は `metadata_db.get_script_content(local_id)` を使う。既存フォルダの取り込み時に限り後方互換で `script.txt` を読んでよい。`videos.output_dir` は `sync_folder_to_db()` のたびに実体パスへ更新する。
- 破壊的操作（アップロード・固定コメント・スケジュール変更）は `confirmed=true` 必須 + 画面確認ダイアログ必須。
- 画像手動差し替え・復元は `confirmed=true` 必須。元画像は `000_backups/image_replacements/` に退避し、履歴は active profile の `metadata.db:image_replacements` に記録する。
- 実装が不安定な機能は `[DISABLED]` / `[dry-run]` として画面とコードコメントに明記し、無効ではなくユーザーに理由を提示する。
- テストは `tests/` 配下に置く（Web UI は `tests/test_web.py`）。外部API実通信が必要なテストはモックまたはskip可能にする。
- **テストは利用者の実データに触れない。** `tests/conftest.py` が `app_base_dir()` をテスト専用の一時フォルダへ差し替え、active profile を1件用意する。実キーや実DBに依存するテストを書かず、APIキーが要る初期化は `dummy_google_api_key` のようなダミーの fixture を使う。`tests/test_test_isolation.py` が保存先の隔離を検査する。
- **作業完了前の検証は `python tools/verify.py` にまとめる。** pytest（ルール検査を含む）と `git diff --check` を途中失敗後も最後まで実行し、末尾に結果を表示する。
- **ルールは `tests/test_rule_guards.py` で機械検査する。** `os.environ` 参照・`script.txt` への言及は、ファイルごとの現在件数を上限として増加だけを止める。違反を直して件数が減ったら、同じ作業で上限表も下げる。次は0件を維持する: ログも再送出もしない `except` 節（`raise_api_error` など記録してから報告する共通関数の呼び出しと Ctrl+C の処理は除く）、`closing()` で囲まない sqlite 接続、未使用・未定義の名前（pyflakes）、画面 JavaScript の空の `catch`、画面スクリプトによる `app.js` / `job_poll.js` 共通関数の上書き、traceback の文字列化。`config.py` 公開定数のコメント、日本語を含む `.ps1` のBOM、`.agents/skills` と `.claude/skills` の対応も同じファイルで検査する。新しい恒久ルールを足すときは、機械検査できるならここへ検査も足す。
- **sqlite の接続は `with closing(接続) as conn, conn:` で使う。** `with 接続 as conn:` は確定・取消しかせず接続を閉じないため、Windows では `settings.db` を掴み続けてバックアップの復元などに失敗する。
- **`data/settings.db` の場所は `core.runtime_env.settings_db_path()` だけで決める。** モジュールごとに `app_base_dir()` から組み立てない。
- **画面の JavaScript でジョブの完了を待つときは `app.js` の `pollJob()`（状態1行の表示なら `pollJobStatus()`）を使い、`setInterval` で写さない。** HTML のエスケープは `esc()` だけを使う。
- Claude Code on the web などのリモート環境では、`.claude/hooks/session-start.sh` がセッション開始時に `config/requirements-dev.txt` を導入する。利用者のPCでは何もしない。
- Starlette 1.1.0以降: `TemplateResponse(request, name, context)` の引数順に従う。
- 設定画面で保存した値はアプリ再起動なしで即時反映する。`config_service._apply_runtime_updates()` で `setattr(cfg, key, value)` と `sys.modules` 全走査による伝搬を行う。`WEB_UI_PORT` など「アプリ起動時に固定されるパラメータ」だけを例外とし、それらは EDITABLE_CONFIG から除外する。UI上に「再起動後に反映」という文言を出さない。

## Web UI チャンネル切替

- Web UIヘッダーに現在の active channel profile（チャンネル名 / ハンドル）を常時表示する。
- Web UI上で登録済み channel profile をいつでも切り替えられること。1つのWeb UIで複数プロファイルを選択・切替できることが完了条件であり、cloneごとに1プロファイルを固定する運用だけでは不十分。
- 固定コメントは Web UI 内では手動投稿のみ（自動投稿ウォッチャーは持たない）。自動投稿は OS タスク（`core/fixed_comment_task.py` が Windows=タスクスケジューラ / macOS=launchd に登録）から `<exe> --post-fixed-comments` を定期実行して行う。対象は `AUTO_FIXED_COMMENT_PROFILE_SCOPE` に従い、`all` の場合は全 channel profile の metadata.db と profile_id 別 YouTube OAuth token を巡回する。失敗は `core/background_task_status.py` に前回結果として保存し、ヘッダーと固定コメント画面に表示する（ログだけで済ませない）。二重投稿は YouTube API を呼ぶ前に `youtube_status.fixed_comment_posted` を条件付き原子 UPDATE で確保（claim）して防ぐ（成立した1プロセスだけが投稿、失敗時は戻す）。タスクは exe 移動などでズレたら起動時に自動修正する。
- active profile 未設定時は YouTube操作とプロンプト生成を禁止する（`require_active_profile()` で例外）。

## プロジェクト概要

複数のYouTubeチャンネル向けに、台本生成・VOICEVOX音声・画像生成・native MP4・YouTubeアップロード・Analytics確認までを行うローカルWebツール。
チャンネル固有の設定はすべて channel profile と関連DBテーブルで管理する。
台本 → VOICEVOX音声 → Nano Banana / Stable Diffusion WebUI 画像 → native MP4 → YouTubeアップロード。

## 実行環境

- Windows / Mac を想定する。動画出力は ffmpeg/native 生成を主経路とする。
- Python 仮想環境: `.venv/`
- 起動: 通常は `start.ps1`（Windows）/ `start.command`（macOS）推奨（手動起動時は `python -m web_app.app --open-browser`）
- VOICEVOX をローカルで起動しておく必要がある（`http://localhost:50021`）

## 主要ファイル

| ファイル | 役割 |
|---|---|
| `web_app/app.py` | FastAPI Web UI エントリポイント |
| `workers/main.py` | `run_pipeline()` — Web UI から呼ぶ1本分の動画生成パイプライン |
| `workers/runner.py` | DB queue から生成・レンダージョブを取得して実行する常駐 runner |
| `config/config.py` | 定数・設定（音声速度・モデル名・パスなど） |
| `core/parser.py` | 台本パーサー `ScriptParser` |
| `core/ai_generator.py` | 台本・タイトルA/B/C案の生成（使う AI は `core/text_llm.py`） |
| `core/text_llm.py` | 文章生成AIの窓口（Gemini / Claude Code CLI / Codex CLI / Ollama）。CLI は読み取り専用の安全指定で起動し、プロンプトは標準入力で渡す |
| `core/comfyui_generator.py` | ComfyUI（ローカル・Krea 2 Turbo）画像生成 |
| `core/codex_image.py` | Codex CLI の画像生成。専用一時フォルダだけ書き込み可・`OPENAI_API_KEY` を外して起動 |
| `core/local_image_compose.py` | ローカル画像の文字入れ・サムネの立ち絵合成（画像AIに日本語を描かせない） |
| `core/voicevox.py` | VOICEVOX音声生成 |
| `core/image_generator.py` | Nano Banana背景・サムネ生成 |
| `core/native_renderer.py` | ffmpeg/native MP4レンダラー |
| `core/opening_quality.py` | 冒頭品質レビュー（ローカル + Ollama + ChatGPT） |
| `core/upload_scheduler.py` | アップロードスロット管理 |
| `core/upload_records.py` | アップロード記録参照 |
| `core/script_prompts.py` | Gemini台本生成プロンプト構築 |
| `core/youtube_analytics.py` | YouTube Analytics API取得 |
| `core/analytics_score.py` | Analytics評価・スコアリング・TSV保存 |
| `core/output_paths.py` | 出力パスの集約・マイグレーション |

## 出力フォルダ構造

```text
output/{profile_id}/          ← active profile の output_root
├── videos/
│   └── {テーマ名}/           ← 生成中・未アップロード
│       ├── {テーマ名}_native.mp4
│       ├── thumbnails/
│       ├── audio/
│       └── backgrounds/
├── 000_uploaded/             ← アップロード済みアーカイブ（履歴にも表示）
├── 000_backups/              ← 生成時のフォルダバックアップ
├── 000_assets/               ← profile 別BGMなどの登録済み素材
└── 000_data/
    └── metadata.db           ← 動画メタ・youtube_status・Analytics・ジョブ履歴（正本）
```

profile 別出力と共通DBの扱いは「チャンネルプロファイル・DB正本」に従う。

## 重要な規約・注意点

### ScriptParser

- メタタイプの判定には必ず `ScriptParser.META_TYPES` を使う（Web UI / `workers/main.py` で共有）
- `parse_string(text)` はメモリ内処理（tempfileを使わない）

### アップロードスロット

- Shorts: 毎日 12/21時
- Long: 毎日 22時
- 投稿予約スロットは `data/settings.db` の `channel_schedule_settings` で profile_id ごとに管理し、既定値は全チャンネル共通（タイムゾーン Asia/Tokyo）
- 予約枠の空き判断と詰め直しはYouTube側の予約状態を正として扱う

### 説明文処理

- VOICEVOXクレジット手書き行は自動除去（警告なし）
- `_VOICEVOX_CREDIT` / `_CHANNEL_FOOTER` を末尾に自動付与

### native Shorts字幕

- 通常字幕は白文字を基本にし、話者差はフチ色で表現する
- ずんだもん: 白文字 + 濃緑の内フチ + 黒外フチ
- 四国めたん: 白文字 + 濃ピンク紫の内フチ + 黒外フチ
- 背景が複雑でも読めるよう、半透明黒帯は残す
- 色付き字幕は全文ではなく重要語の強調に限定する

### gitignore対象（コミット禁止）

- `output/` 全体
- `dev/` — 開発用テストファイル（後述）
- `.env`
- `client_secrets.json`
- `token.json`
- `token_analytics.json`
- `data/secret_master.key` — DPAPI保護マスターキー（個人PC専用）
- `data/settings.db` / `data/settings.db-wal` / `data/settings.db-shm` — 設定DB（認証情報の暗号化エントリを含む）とSQLite補助ファイル
- `data/web_ui.lock` / `data/web_ui_instance.json` — Web UI の多重起動防止ロックと起動中URL
- 認証情報、APIキー、OAuthトークン、秘密鍵、Cookie、個人用設定などのシークレットはファイル名に関わらずコミット禁止。ドキュメントやログにも値を記載しない。

### テスト用ファイルの置き場所

- 動作確認用の一時画像・動画・スクリプトなど「リポジトリに入れたくないテスト系ファイル」はすべて `dev/` フォルダに置く。
- `dev/` は `.gitignore` で除外済みのため、コミットされない。
- `assets/` 直下やサブフォルダにテスト画像を置かない。テスト用途のものは必ず `dev/` に移動してから使う。

