# 変更履歴

このファイルには、現行アーキテクチャ以降の運用や品質に影響する大きめの変更だけを残します。

---

## 2026-06-06

### 食べ物・都市伝説台本を掛け合い中心から説明中心へ刷新

- 通常Shorts / Long共通の「説明密度・掛け合い品質ルール」を追加し、機械的な交互会話、相槌、復唱、同意、情報が増えない押し問答を禁止した。ずんだもんは2〜5行続けて具体情報を説明でき、めたんは説明役ではなく視聴者目線の疑問・違和感・既知ネタ臭・構成の弱さを突く役に固定した。
- 食べ物雑学では昔の扱い・製法・包装・商品開発・海外差と「なぜそうなったか」、都市伝説では時代・場所・目撃談の型・噂の広まり方・怪談構造を必須の具体性として追加した。`zunkami` / `food_trivia` / `zundamon_kowai` / `urban_legend` を同じ方針へ同期した。
- 高テンポルールに残っていた「掛け合い・驚きリアクション優先」を修正し、新しい具体情報と展開の切り替えでテンポを作る方針へ変更した。
- Ollama冒頭レビューとChatGPT生成前レビューへ、相槌・復唱、めたんの説明役化、機械的交互会話、説明不足、ジャンル固有の具体性を追加した。同一話者4連続をNGにする旧条件は、ずんだもんの連続説明を許可するため撤廃した。
- 起動時seederが対象ジャンルの既存デフォルト台本・ネタ会議テンプレートを現行ルールへ同期するようにした。

### Shorts投稿枠を12時・21時へ変更

- 食べ物雑学（`zunkami`）と都市伝説（`zundamon_kowai`）を含む全チャンネル共通のShorts既定投稿枠を `07:00 / 12:00 / 21:00` から `12:00 / 21:00` へ変更した。Longは従来どおり `22:00`。
- `channel_schedule_settings` の移行キーを更新し、既存プロファイルの個別設定も新しい既定値へ更新する。固定コメント自動投稿タスクは新スロットの5分後へ再登録する。

### 固定コメント自動投稿時のコンソール表示を抑止

- Windowsタスクスケジューラから固定コメント自動投稿を実行するとき、アプリ本体を直接起動せず、非表示PowerShellから子プロセスも `WindowStyle Hidden` で起動するようにした。定期実行時にコマンドプロンプト画面が表示されない。
- 旧形式の登録済みタスクは起動時の不整合検出で自動再登録する。

---

## 2026-06-05

### Ollamaによるジャンル別再生リスト自動登録と固定コメント一括記録を追加

- 台本に `再生リスト:` がないアップロードでも、アップロード前に Ollama（`OLLAMA_PLAYLIST_MODEL`）で active profile の `playlist_categories.md` からカテゴリを1件判定し、動画形式別のYouTube再生リストを自動作成・登録するようにした。候補外カテゴリは採用せず `E-PLAYLIST-CLASSIFY` で停止する。
- アップロード画面で、同名の既存再生リストを「活かす」か「削除して作り直す」か選べるようにした。作り直しは確認ダイアログで明示し、バッチ内で同じ再生リストを何度も削除しない。
- 固定コメント画面に「未投稿をすべて投稿済みにする」を追加し、YouTube APIで実投稿せず `youtube_status.fixed_comment_posted` を一括更新できるようにした（`confirmed=true` 必須）。

### 台本方針を「説明優先」へ刷新（都市伝説・食べ物雑学 共通）

- ずんだもんとめたんを無理に交互に喋らせず、会話量より情報密度を優先する方針へ変更。意味のない押し問答・情報が増えない掛け合い・抽象返し・リアクションだけの会話・テンポのためだけの短文連打を禁止（全形式共通）。`config/prompt_profiles/genres/{zundamon_kowai,zunkami,food_trivia}/script_context.md`。
- ずんだもんは2〜5行続けて具体的に説明してよい。めたんは本当に視聴者が引っかかる点だけ突っ込み、ツッコミ直後は必ず具体情報で返す（抽象語だけで逃げない）。
- Long専用ルール: 掛け合いで尺を埋めることとShorts的な短文連打を禁止。各チャプターに「具体情報・代表例・なぜ怖いのか/理由や昔との違い・視聴者の日常との接点」を必須化し、1チャプター最低1つの「知らなかった」具体ネタを要求。掛け合いリズムと物語構成の基本形を明記。
- 既存チャンネル（zundamon_kowai・zunkami）の保存済み台本テンプレ（system_rules）も、未編集のものに限り新ルールへ更新済み。

### キャラクター設定の長文フィールド自動拡大と空欄の自動補完

- 役割・口調・話し方ルール・禁止表現・掛け合いルールの textarea が小さく長文がスクロールに押し込まれていたため、内容に合わせて高さが自動で伸びる＋手動リサイズ可にした（`web_app/templates/settings.html`）。
- 旧seedで作成され音声・立ち絵・クレジットが空のままだった既存キャラを、seed既定値で**非破壊的に補完**する `backfill_character_profiles_from_seed()` を追加し、起動時の `ensure_character_profiles_all()` から呼ぶようにした。話者が一つでも設定済みのキャラ（ユーザーが触った形跡があるもの）は対象外。
- これにより、ずんだもん・四国めたん等の話者ID・表情別スタイル・立ち絵・クレジットがキャラクター設定画面に正しく表示される。

### キャラクター設定画面をキャラごとのタブ表示に変更

- 設定＞キャラクター設定が全バリアントを縦に並べるグリッド表示で見づらかったため、キャラ名ごとのサブタブに整理した（`web_app/templates/settings.html`）。
- 同じキャラ名のバリアント（有効化1件のみ使用）は同じタブ内にまとめ、タブには有効/無効バッジとバリアント件数バッジを表示。保存・有効化・削除後も選択中のタブを保持する。

### めたんの立ち絵がマイクを持った差分になる不具合を修正

- nativeレンダーのめたん画像が、四国めたんPSDの腕グループで「マイク」差分が既定表示のまま合成され、マイクを持った立ち絵になっていた。
- 原因は腕の「普通」正規化を `"四国めたん" in ファイル名` で判定しており、配布用に `metan.psd` へリネームされると判定が外れて正規化がスキップされていたこと（`core/native_character_assets.py`）。ファイル名依存をやめ、キャラクター識別フラグ `normalize_arms` で制御するようにした。
- あわせて差分オーバーレイ生成の `finally` で早期return時に未定義変数を `del` して `UnboundLocalError` を出していた既存バグも修正（変数をNone初期化）。
- キャッシュにバージョン管理（`_CACHE_VERSION` ＋ `.cache_version` マーカー）を導入し、生成ロジックを変えたら旧キャッシュPNGを**自動削除して再生成**するようにした。旧マイク画像の手動削除は不要。

### 環境変数パースのフォールバックにdebugログを付与

- `config/config.py` の選択肢リスト解析失敗・`THUMBNAIL_HOLD_FRAMES_SHORTS` 解析失敗のフォールバックに debug log を追加し、無言フォールバックを解消した。

### 残存サイレント例外ハンドラへログを付与

- 全コードベースを AST で走査し、ログも再送出もしないサイレントな例外ハンドラを洗い出した。診断時にスタックトレース／原因が失われていた箇所へ既存規約 `_logger.<level>(..., exc_info=True)` でログを追加。
- 対象: 予約公開の `published_at` 解析失敗フォールバック（`core/upload_scheduler.py`）、余剰WAV削除失敗・既存テーマ退避失敗・生成前レビュー失敗（`workers/main.py`）、ジョブログのミラー失敗・レンダーキャンセル（`workers/runner.py`）。
- キャンセル／`KeyboardInterrupt` の正常系、プロセス走査中の `psutil` 例外（ログspam源）、後段で集約報告される例外は意図的に対象外とした。

### キャラクターseedのジャンル判定を設定化

- `script_prompts.py` に置かれていた食べ物系 genre_profile 判定を `config/config.py` の `CHARACTER_FOOD_TOXIC_GENRE_PROFILES` へ移し、辛口相方めたんを既定有効にするジャンルを環境変数で調整できるようにした。

### Web API例外ログの共通化を拡張

- プロンプトテンプレートAPIの作成・更新・複製・削除・インポート失敗も `raise_api_error()` 経由にし、HTTPエラーへ変換する前に debug log へ原因を残すようにした。
- 履歴削除と履歴フォルダを開く操作の失敗も `raise_api_error()` 経由にし、ユーザー向けメッセージを維持しながら debug log に原因を残すようにした。
- Analytics API のライセンス確認失敗と YouTube Analytics 維持率取得失敗も `raise_api_error()` 経由にし、HTTPエラー変換前に debug log へ原因を残すようにした。
- チャンネルプロファイルAPIの作成・更新・有効化・削除失敗も `raise_api_error()` 経由にし、HTTPエラー変換前に debug log へ原因を残すようにした。
- 設定APIの AquesTalk テスト音声生成失敗とバックアップ復元失敗も `raise_api_error()` 経由にし、HTTPエラー変換前に debug log へ原因を残すようにした。

### profile 解決の無言 default 降格を縮小

- Google / OpenAI / Hugging Face など profile 単位の認証情報を参照する処理で、active profile 未設定時に `"default"` へ落ちる経路を廃止した。`core.secret_store.require_current_profile_id()` を追加し、未設定時は `NoActiveProfileError` で停止する。
- SDモデル画面の表示用 HF_TOKEN 状態は active profile 未設定時に `False` として扱い、画面表示だけで default profile の認証状態を参照しないようにした。
- 投稿スケジュール取得も active profile 未設定時に default スケジュールを返さず、profile 設定エラーとして停止するようにした。
- `prompt_profile_loader` の genre profile 設定読み込みでも、未知ジャンル時に空値へ落ちず `GenreProfileNotFoundError` で停止するようにした。
- `AIGenerator.generate_script()` は Google API キー未設定時に `"Error: ..."` 文字列を返さず、エラーコード付き例外で停止するようにした。
- `metadata.db` パス解決も active profile 未設定時に旧 `OUTPUT_DATA_DIR` へ戻らないようにし、別チャンネルや旧互換DBへ誤って書き込まないようにした。
- Web API の例外変換ヘルパー `web_app.routes.errors.raise_api_error()` / `error_payload()` を追加し、BGM / キャラクター設定 / 画像差し替え / SDモデル API の失敗を必ず debug log に残してからエラーレスポンスへ変換するようにした。
- `workers.main` の出力フォルダロック診断を `workers.output_locks`、`core.native_renderer` の ffprobe 尺取得を `core.media_probe` へ切り出し、巨大ファイルの責務を一部整理した。

---

## 2026-06-04

### エラーコード管理とデバッグログ運用を強化

- ユーザー操作で停止する設定系エラーを `E-PROFILE-MISSING` / `E-PLAYLIST-CONFIG` / `E-METADATA-CONFIG` として `core/error_codes.py` に追加し、active profile 未設定やジャンル設定欠落を安定したエラーコードで返すようにした。
- 再生リスト解決とYouTubeメタデータ生成で、active profile 未設定時に古い食べ物チャンネル設定へ無言フォールバックする経路を廃止した。
- 生成・画像生成・YouTubeアップロード・Analytics・スケジュール・サービスチェックの失敗経路に debug logging を追加し、画面表示やジョブログだけで原因が残らない箇所を減らした。
- ffmpeg / ffprobe / PowerShell / schtasks / AquesTalk など外部コマンドの出力読み取りで `encoding="utf-8", errors="replace"` を明示し、Windows環境の文字コード差で診断やダッシュボード表示が警告を出さないようにした。
- `AGENTS.md` に、ユーザー向け停止エラーは `ERROR_CATALOG` へ登録し、例外捕捉・許可フォールバック・失敗扱いの経路では必ず `logging` に原因と対象を残すルールを追記した。

### YouTube認証の未設定profileフォールバックを禁止

- YouTubeアップロード / YouTube Analytics の認証 profile 解決で、active profile 未設定時に `"default"` へ落ちる古い後方互換フォールバックを廃止した。profile 未設定時は明示エラーで停止し、別チャンネルの認証情報を誤って参照しないようにした。
- exeパス互換の旧 `assets` 絶対パス救済は、同梱対象の `assets/characters/` と `assets/sd_webui/` に限定した。外部素材フォルダ内の unrelated な `assets/` パスは勝手に同梱リソース扱いしない。

### exe配布時のパス参照を相対化・永続領域へ整理

- キャラクター立ち絵のDB保存値を `asset:assets/characters/reimu.png` 形式に対応させ、同梱リソース配下の絶対パスを保存時に `asset:` 参照へ正規化するようにした。native レンダラーは使用直前に `resource_base_dir()` 基準で解決するため、onefile の一時展開先が変わっても stale path にならない。
- native 立ち絵のPSD展開キャッシュを同梱 `assets/characters/_native_cache/` から `data/native_character_cache/` へ移動し、exe 終了で消える一時展開先や読み取り専用リソース配下へ書かないようにした。
- `AQUESTALK_ENGINE_PATH` と Stable Diffusion WebUI モデルマニフェストは相対パス保存・実行時解決に対応した。アプリ配下の絶対パスは保存時に相対化し、外部ドライブや別アプリ本体など理由があるものだけ絶対パスを残す。既定マニフェストは既存の `assets/sd_webui/model_manifest.json` を `resource_base_dir()` 基準で読む。
- ビルド時生成ファイル `core/_build_version.py` をリポジトリ追跡から外し、`build_exe.ps1` が生成する ignored ファイルとして扱うようにした。ビルドのたびに作業ツリーが汚れる問題を防ぐ。

### 固定コメント自動投稿をOSタスクへ一本化（Web=手動投稿のみ）

- **方針変更**: Web UI 内の固定コメント自動投稿ウォッチャーを廃止し、Web は手動投稿のみに。自動投稿は OS タスク（Windows=タスクスケジューラ / macOS=launchd）経由に切り分けた。`AUTO_FIXED_COMMENT_ENABLED` 設定は撤去。
- 投稿の中核を job_manager/runner 非依存の `fixed_comment_service.post_fixed_comment_now()` に切り出し、`auto_fixed_comment_service.post_all_pending()` で対象プロファイルの未投稿分を直接投稿。CLI `<exe> --post-fixed-comments` を追加（アプリ非起動でも投稿）。
- **二重投稿防止**: YouTube API を呼ぶ前に `fixed_comment_posted` を条件付き原子 UPDATE で確保（claim）。SQLite の直列化により完全同時実行でも成立した1プロセスだけが投稿し、失敗時は claim を戻す。
- `core/fixed_comment_task.py` で OS タスクを登録/解除（実行時刻=予約スロット＋5分）。**タスク名にインストールディレクトリ識別子（リーフ名＋パスのハッシュ）**を含め、同一PCの複数インストールを区別。exe 移動などで生じたズレ・迷子タスクは `inspect()`/`repair()` で検出し、アプリ起動時に自動修正（＋設定画面の「見つけて修正」）。
- 設定画面（製品管理タブ）にON/OFFトグルと修正、API `GET/POST /api/settings/fixed-comment-task`・`POST .../repair` を追加。

### アプリバージョンの動的化とWeb UI表示

- バージョンの日付部分をハードコード（`APP_VERSION_BASE="2026.05.19"`）から HEAD コミット日付の動的取得に変更し、化石化しないようにした（`{コミット日付}.{コミット数}-{hash}`）。開発時は git から算出し、古い焼き込み `_build_version.py` を優先しない。exe(frozen)時のみ焼き込みを優先する。
- `build_exe.ps1` も同じ規則でコミット日付からバージョンを焼き込むよう更新。
- Web UI 右下に常時バージョンを小さく表示するようにした。

### 出力先フォルダを設定で変更可能にした

- 全プロファイル共通の出力ベースディレクトリを設定 `OUTPUT_BASE_DIR`（設定 DB 保存）で変更できるようにした。既定はリポジトリ直下 `output/`。別ドライブ等への移設に対応する。
- 変更時は既存の出力一式（各 profile フォルダ・metadata.db）を新ベースへ自動移動する `output_paths.relocate_output_base()` を追加。実行中/待機中ジョブがある場合は移動せず拒否し、移動先の同名衝突・現ベースとの入れ子指定も拒否する。
- 初回セットアップ画面「7. 出力先フォルダ」と設定画面の製品管理タブ「出力先フォルダ」、API `GET/POST /api/settings/output-base`（`POST` は `confirmed=true` 必須）から変更できる。
- 併せて、生成時の既存テーマ退避先がプロファイルを無視した相対パス `output/000_backups` に固定されていた不具合を修正し、active profile の `output_root/000_backups`（`get_backups_dir()`）へ退避するようにした。

### AquesTalk系ゆっくり音声バックエンドを追加

- 音声生成に `voicevox` / `aquestalk` のバックエンド解決層を追加した。台本の各セリフは active profile のキャラクター設定から音声バックエンドを解決し、VOICEVOXまたはAquesTalk系エンジンでWAV生成する。
- AquesTalk設定（有効フラグ、エンジンパス、ライセンス確認済みフラグ、コマンドテンプレート、速度・高さ・音量、タイムアウト）を設定DBで管理し、ライセンスキーは `encrypted_secrets:aquestalk_license_key` に暗号化保存する。AquesTalk有効時のサービスチェックと霊夢テスト音声生成APIを追加した。
- 霊夢・魔理沙seedをVOICEVOX前提から外し、AquesTalkの `ゆっくり霊夢風` / `ゆっくり魔理沙風` として無効状態で追補する。AquesTalkが未設定・未配置・ライセンス未確認・生成失敗の場合はVOICEVOXへ自動代替せず明示エラーで停止する。

### READMEに製品版向け動作環境を追加

- Windows版 / Mac版それぞれの最低・推奨・ローカル画像生成向け動作環境を追加した。Google AI画像生成モードでは高性能GPUが必須ではなく、Stable Diffusion WebUIによるローカル画像生成ではGPU性能とメモリ容量の影響が大きいことを明記した。
- 必要な外部ソフト・サービスと注意事項を整理し、複数ジャンル対応のローカルWeb UIアプリとして利用前にPC性能と外部依存を判断できるようにした。

### キャラクターごとの必要クレジット設定を追加

- `character_profiles` に `credit_required` / `credit_text` を追加し、設定画面「キャラクター設定」タブからキャラごとの説明文クレジット要否と表記を編集できるようにした。
- 説明文末尾の「使用音声合成」は固定のずんだもん・めたん表記ではなく、台本で実際に発話したキャラの設定から重複なしで組み立てるようにした。VOICEVOX以外の音声アプリを追加する場合も、クレジット表記をキャラ設定側で持てる。

### 霊夢・魔理沙と音声バックエンド設定をキャラクター管理へ追加

- キャラクター設定に `voice_backend` / `voice_speaker` / `voice_speaker_id` / `voice_styles_json` / `portrait_png_path` を追加し、設定画面からキャラごとの音声アプリ種別・話者ID/名前・表情別話者ID・立ち絵PNGパスを編集できるようにした。
- 初期キャラseedに霊夢・魔理沙を無効状態で追加した。新規チャンネルや既存チャンネルへの追補で、必要なときに有効化して台本生成プロンプトとnative立ち絵へ参加させられる。
- 音声生成は active profile のキャラ設定から VOICEVOX speaker ID を解決するようにした。VOICEVOX以外のバックエンド名も設定として保存できるが、生成アダプタ未実装のため使用時は明示エラーで停止する。

### キャラクター設定画面を追加・削除まで使える管理画面に拡張

- 設定画面「キャラクター設定」タブを、カード一覧・有効トグル・追加フォーム・削除ボタンを備えた管理画面に拡張した。表示名 / キャラ名 / 並び順 / 役割 / 口調 / 話し方ルール / 禁止表現 / 掛け合いルールを画面から編集できる。
- 有効トグルで保存した場合は一覧を即再読み込みし、同名キャラの排他有効化（片方を有効にすると他方が無効）を画面へ反映する。
- キャラ設定欄のHTMLエスケープを強化し、入力値に `<` / `>` が含まれても画面構造が壊れないようにした。

### キャラクター設定の同名バリアント切替を排他化・シャットダウンテストを安定化

- キャラクター設定で `enabled=true` にしたとき、同じチャンネル・同じ `character_name` の他バリアントを自動で無効化するようにした。四国めたんの「辛口相方」と「お嬢様毒舌」が同時に台本プロンプトへ混ざる事故を防ぐ。
- `core.app_shutdown.request_shutdown(..., async_shutdown=False)` を追加し、終了処理をテストで同期実行できるようにした。pytest 実行中は uvicorn 参照なし時のシグナル停止フォールバックを抑止し、テストプロセスが落ちないようにした。
- runner 終了失敗や metadata DB パス互換フォールバックを debug ログへ残すようにし、無言フォールバックを減らした。

### キャラクター設定で四国めたんを切替可能に（辛口相方 ⇄ お嬢様毒舌）

- 各チャンネルに四国めたんの両バリアント（`metan_food_toxic`＝辛口相方／`metan_standard_toxic`＝お嬢様毒舌）を投入し、ジャンル既定の片方だけを有効にした。設定画面「キャラクター設定」タブのトグルで切替できる（同名キャラは1つだけ有効にする運用）。起動時の追補で既存チャンネルにも両バリアントを用意する（冪等・追補式）。

### キャラクター設定の管理UIを追加

- 設定画面に「キャラクター設定」タブを追加。active channel のキャラ設定（役割・口調・話し方・禁止表現・掛け合い）の編集と有効/無効切替ができる。`GET/PATCH/POST/DELETE /api/character-profiles`（`web_app/routes/api_character_profiles.py`）。別 profile のキャラ設定は変更できない（404）。

### キャラクター設定を台本テンプレートから分離・食べ物雑学堂のめたんを辛口相方ツッコミ化

- **キャラクター設定を台本テンプレートから分離**した。役割・口調・禁止台詞・掛け合い構造を `data/settings.db` の `character_profiles` テーブル（`core/character_profile_store.py`）で channel 別に管理し、生成時に `compose_character_section()` で台本プロンプトへ合成する。台本テンプレート（`script_rules`）は動画構成・尺・分量・出力形式だけを持つ。
- **四国めたんを辛口相方ツッコミ設定として独立管理**。食べ物雑学堂（genre `zunkami` / `food_trivia`）は「辛口相方（ずんだハウス風）めたん」（`metan_food_toxic`）を既定で適用。「ですわ」連発・お嬢様口調をやめ、「あんた」「〜じゃん」「〜だろ」等の短く雑なツッコミにする。復唱・同意・補足・説明・驚きだけの台詞を禁止。
- **情報はずんだもんが出し、めたんが引き出す構造**に統一。情報・理由・答え・結論はずんだもん、めたんは浅さ・既知ネタ臭・構成の弱さ・視聴者の疑問を短く突っ込む役割に固定。
- **チャンネル分離**: 都市伝説（`zundamon_kowai`）は従来の「お嬢様毒舌めたん」（`metan_standard_toxic`）を維持。食べ物雑学堂の設定は混入しない。ネタ会議（meeting）テンプレートにも注入しない（`METAN_TSUNDERE_RULES` は meeting のみで使用）。
- **自動フォールバック禁止**: 有効なキャラ設定が無いチャンネルは例外（標準めたんへ戻さない）。起動時に既存チャンネルへキャラ設定を保証し、旧テンプレートに直書きされたキャラ長文を除去する移行を実行（冪等）。

### Nuitka exe ビルドの準備（frozen 対応・ビルドスクリプト）

- `core/runtime_env.py` を追加（`is_frozen()` / `app_base_dir()`）。exe(onefile) では `__file__` が一時展開先になるため、永続データの基準を exe フォルダに anchor する。
- `core/secret_store.py` / `core/settings_store.py` の `data/settings.db`・マスターキーを `app_base_dir()` 基準に変更（**開発時の挙動は不変**、exe 時のみ exe フォルダ直下に永続化）。
- `web_app/app.py`: frozen 時は job-runner を `exe --run-runner` で起動（`python -m workers.runner` の代替）。`main()` 先頭で `--run-runner` を処理。
- `core/gui_support.py: build_app_version()`: ビルド時焼き込み `core/_build_version.py`（gitignore）を最優先。
- `build_exe.ps1`（Nuitka onefile・データ同梱）と `BUILD.md`（手順・既知の残課題）を追加。`.gitignore` にビルド成果物を追加。実コンパイルは未実施（準備段階）。

### 生成前にディスク空き容量チェックを追加（E-DISK）

- 動画生成ジョブ登録（`POST /api/generate` 単発/バッチ）の前に、出力先ドライブの空きが `DISK_MIN_FREE_GB`（既定 2GB、0 で無効）未満なら `E-DISK`（対処手順つき）で 422 停止する。`core/disk_check.py`。初回セットアップのサンプル生成（`setup_test`）は対象外。

### 初回セットアップ完了に最小構成の必須チェックを追加

- セットアップ完了（`POST /api/settings/setup`）に、法務同意に加えて**最小構成（active channel profile / VOICEVOX 接続 / ffmpeg 利用可）の充足を必須化**。未充足なら 422 で不足項目を返す。`web_app/services/status_service.py:setup_readiness()` / `GET /api/settings/setup-readiness`。
- `/setup` の完了欄に「必須条件を確認」ボタンを追加。Google API キーは使い方次第のため必須にしない（手書き台本＋Stable Diffusion WebUI なら不要）。

### サポート導線・更新確認を製品管理タブに追加

- 設定画面「製品管理」にサポート問い合わせ先（`PRODUCT_SUPPORT_URL` / `PRODUCT_SUPPORT_EMAIL`、空=非表示）を診断パッケージ付近に表示。`GET /api/settings/product-info`。
- 更新確認機能を追加（`core/update_check.py`、`POST /api/settings/check-update`）。`PRODUCT_UPDATE_CHECK_URL` を設定したときだけ最新版JSON（`{latest_version, url, notes}`）を取得して現在ビルドと比較する。**未設定（既定）ではネットワークアクセスしない**。

### 初回セットアップの最初に法務同意（利用規約・EULA・プライバシーポリシー）を必須化

- `/setup` の冒頭に同意カードを追加。利用規約 / 使用許諾（EULA）/ プライバシーポリシー / 特定商取引法に基づく表記へのリンクと同意チェックを表示する。
- 文書は `GET /legal/{doc}`（`core/legal_consent.py:LEGAL_DOCUMENTS` のホワイトリストに限定、任意パス読み取り不可）で閲覧。`web_app/templates/legal.html` で表示。
- 同意は `data/settings.db:settings`（`LEGAL_CONSENT_ACCEPTED` / `LEGAL_CONSENT_AT`）に記録。**未同意ではセットアップ完了（`POST /api/settings/setup`）を 422 でブロック**する＝生成・アップロードも解禁されない。
- `/legal` は setup リダイレクトミドルウェアの除外に追加（active profile 未設定でも閲覧可）。

### 表記を「Stable Diffusion WebUI」に統一・必須構成早見表をREADMEにも記載

- UI・コメント・ログ・ドキュメントの「SD WebUI」「Forge（単独）」「SD（略語）」表記を「Stable Diffusion WebUI」に統一した（命名ルール準拠）。識別子 `SD_WEBUI_*` は対象外。
- 必須構成 早見表（使い方別の必要ソフト・APIキー）を README の前提条件にも追加した（`/setup` 冒頭と同内容）。

### Stable Diffusion WebUI 使用時は Ollama を必須化（プロンプト英訳）

- Stable Diffusion WebUI 画像生成は日本語プロンプトの英訳に Ollama を使うため、Ollama 未起動・接続不可時は生のエラーではなく `E-OLLAMA-DOWN`（対処手順つき）で明確に停止するようにした（`core/image_generator.py:_translate_to_english_for_sd`）。背景生成エラー表示でも `AppError.user_message()` で対処手順を出す。
- `E-OLLAMA-DOWN` の文言を「品質レビュー専用」からバックエンド非依存に変更し、Stable Diffusion WebUI 英訳でも使う旨を明記した。
- `/setup` のインストール案内で、Ollama は「品質レビューは任意・Stable Diffusion WebUI 使用時は必須」と明示し、Stable Diffusion WebUI の手順にも Ollama 導入を追記した。

### /setup にソフトウェアのインストール案内を追加・APIキーの必要条件を明記

- `/setup` に各外部ソフト（VOICEVOX / ffmpeg / Ollama / Stable Diffusion WebUI）のインストール案内カードを常時表示するようにした（用途・必須/任意・ダウンロードリンク・手順・補足）。`core/service_detector.py:get_installation_guides()` を追加。
- APIキーの必要条件を `/setup` に明記した。Google API キーは AI台本生成（Gemini）と Gemini 画像生成に使うが、**台本を手書きし画像を Stable Diffusion WebUI で作るなら不要**。YouTube 認証は**アップロード時のみ必要**で生成だけなら不要。OpenAI / HF Token は任意。必須は VOICEVOX・ffmpeg のみ。

### 生成パイプラインのエラー文言を対処手順つきに改善（VOICEVOX未起動・ffmpeg未検出）

- VOICEVOX 未起動・タイムアウト時、生の `ConnectionError`（urllib3 のスタック）ではなく `E-VOICEVOX-DOWN`（「VOICEVOX を起動してください」等の対処手順つき）を表示するようにした。`core/voicevox.py` の POST を `_post()` で包み、音声クエリ・合成の失敗表示（`workers/main.py`）で `AppError.user_message()` を使う。
- ffmpeg バイナリ未検出時、`[WinError 2]` ではなく `E-FFMPEG-MISSING`（PATH 追加 / FFMPEG_BIN 指定 / `/setup` 自動検出の案内つき）を表示するようにした（`core/native_renderer.py:_run_ffmpeg` / `_run_ffmpeg_capture`）。
- 診断パッケージのエラーカタログに `remediation`（対処手順）も含めるようにした。
- YouTube 認証エラー時の誤誘導ヒントを修正した。認証は DB（`encrypted_secrets`）へ移行済みで `token.json` は使わないため、「token.json を削除して再認証」（存在しないファイル）の案内を、設定画面「APIキー」タブでの再認証案内に置き換えた（コメント投稿 / 公開予定変更 / 再生リスト追加 / スケジュール画面）。
- ホーム画面で必須サービス（VOICEVOX / ffmpeg）未接続時に `/setup`（ダウンロード先・自動検出）への誘導ヒントを表示するようにした。
- いずれも失敗時のメッセージ改善・誘導追加のみで、成功時の挙動・APIは不変。

### 製品化に向けた4機能を追加（外部依存導線・エラー対処・購入導線・起動自己回復・クロスPC復元）

- **外部依存のインストール導線**: `/setup` の外部サービス診断で、未検出の VOICEVOX / ffmpeg / Ollama / Stable Diffusion WebUI にダウンロードリンクとインストール手順、必須/任意の区別を表示するようにした。DL URL は `config.py`（`VOICEVOX_DOWNLOAD_URL` 他）で差し替え可能。同梱せず個別入手する方針。
- **エラー文言の総点検**: `core/error_codes.py` の全エラーに対処手順（`remediation`）を必須化し、外部サービス稼働・ネットワーク・YouTube認証・セットアップ未完了・ライセンス上限・ディスク不足などのコードを追加した。`format_error(..., with_fix=True)` と `AppError.user_message()` で「何が起きたか＋対処」を提示し、Web の未処理 `AppError` は 422 で対処手順つきレスポンスを返すようにした。
- **試用→購入の動線（UX先行）**: `get_license_info()` に `purchase_url` / `upgrade_available` を追加。trial・上位余地がある場合に設定画面「製品管理」へ購入リンクを表示し、上限到達エラー文言に購入導線（`PRODUCT_PURCHASE_URL`）を付けるようにした。実キー検証はライセンス機能実装時に後付け。
- **多重起動・ポート競合の自己回復**: `/health` に自アプリ識別子を付け、既定ポートが他アプリで使用中なら自動で空きポートへ退避、本アプリが既に起動中なら二重起動せず既存ウィンドウを開くようにした。起動直前のレースでポートを奪われた場合も1度だけ空きポートで再試行する。明示 `--port` 指定時はユーザー意図を尊重してエラー停止する。
- **バックアップ/復元のクロスPC対応**: バックアップ時にパスフレーズを指定すると、認証情報（`encrypted_secrets`）を PBKDF2 + AES-GCM で再暗号化して同梱し、別PCでも同じパスフレーズで復元できるようにした（復元先のマスターキーで保存し直す）。パスフレーズ空欄時は従来どおり同一PC専用。`core/secret_store.py` に `export_secrets_with_passphrase()` / `import_secrets_with_passphrase()` を追加。

---

## 2026-06-03

### 履歴詳細: MP4未生成時にアップロード不可の理由を表示

- MP4が無い動画の履歴詳細でアップロードボタンが**黙って消える**ため「ボタンがなくなった」と誤解されていたのを改善。MP4未生成時は理由（「動画再作成（レンダーのみ）」でMP4を作る導線）を明示するようにした。ボタンの表示条件（`has_mp4`）自体は変更なし。

### レンダー成功の誤判定修正＋ジョブ失敗を debug ログへ集約

- レンダージョブ成功時、MP4は生成できているのに **「❌ 生成が原因不明で終了しました（結果メッセージが空です）」** で failed 扱いになっていたのを修正。`_run_render` の戻り値に `message`（`✅ MP4 生成完了: …`）が無く、`_result_error_message` が空メッセージを失敗と誤判定していたため。成功時も必ず結果メッセージを返すようにした。
- ジョブ失敗が **job ログにしか出ず debug ログ（`app_debug_runner.log`）に出ていなかった**のを修正。全ジョブ（generate / render / 未知種別）の失敗が必ず通る `_run_job` の funnel で、例外経路（スタックつき）・結果メッセージ異常経路の双方を `_logger.error` に記録し、完了行も failed のときは error レベルで残すようにした。

### サムネイル生成失敗の文言を判別可能なエラーコード表示に統一

- サムネイル生成失敗時に、原因（503混雑）と無関係な「接続・残高を確認してください」という**誤誘導の汎用文言＋生トレースバック**を出していたのを修正。残高切れだと誤解させる表示をやめた。
- `generate_thumbnail()` が失敗を握りつぶして `None` を返していたのをやめ、分類済みの `ImageGenerationError`（backend / category / HTTP）を上位伝播するようにした。`run_pipeline` 側の `_report_thumbnail_failure()` が **backend（Gemini / Stable Diffusion WebUI）と種別（混雑 / クォータ・残高 / 認証 / その他）を判別**して表示・記録する。
- 失敗を **debug ログ**（`_logger.error` にスタックと code/backend/category/HTTP）と **job ログ**、`image_generation_failures`（`prompt="thumbnail"`）に記録するようにした（従来はデバッグログに出ていなかった）。
- `core/error_codes.py` に `format_image_error()` / `backend_label()` を追加。エラーコード文言（`E-IMG-BUSY` / `E-IMG-QUOTA` / `E-IMG-AUTH` / `E-IMG-FAIL`）を、残高切れと一時混雑を取り違えないよう明確化した。

### 製品版MVP向けの初回設定・ライセンス・保守機能を追加

- active channel 未作成またはセットアップ未完了の新規環境を `/setup` へ誘導し、チャンネル作成、APIキー登録状態確認、VOICEVOX / ffmpeg / Ollama / Stable Diffusion WebUI 診断、BGM登録、サンプル台本生成を順に進められるようにした。未完了時も設定画面は開けるが、生成・アップロードは明示的にブロックする。
- `data/settings.db` にライセンス edition を保存し、未登録時は trial として扱うようにした。edition に応じて透かし、1日生成本数、channel profile 数、YouTubeアップロード、Analytics、テンプレート数上限を制御する。
- 設定画面に製品管理タブを追加し、診断パッケージ作成、バックアップ作成、復元、セットアップ完了状態、ライセンス設定を管理できるようにした。診断ZIPは秘密情報・台本本文・生成動画・画像を含めず、設定値やジョブログはマスクして保存する。
- バックアップは `data/settings.db` と各 profile の `metadata.db` を対象にし、復元前に現在DBを自動退避する。schema version が安全に扱えない場合は fail closed で中止する。
- 初期データ類を `config/SEED/` に寄せ、製品版テンプレートパックを `config/SEED/prompt_packs/product/` として分離した。製品版seedには `@zunkami` 食べ物雑学専用テンプレートや実績入りテンプレートを含めない。

### 販売版で開発者向け設定をサーバー側で非表示にするフラグを追加

- `DEVELOPER_TOOLS_ENABLED`（`config/config.py`、既定1）を追加。`0` で管理者設定タブ・「開発者」表示モード・edition切替デバッグUIを **テンプレート描画時に出力しない**。
- 併せて `admin` 指定の設定項目を `get_editable_config()` から除外し、`save_config()` も拒否する。表示モードは localStorage 依存で秘匿にならないため、サーバー側フラグで保護する。

### 初回セットアップのサービス自動検出・透かし/バックアップの堅牢化

- 初回起動（active profile 未設定）で `/setup` が 500 になっていた不具合を修正（`get_settings_status` が output_dir 解決で `require_active_profile` を呼んでいた）。未設定時は output_dir を空にして状態表示する。
- `/setup` に「プロセスを走査して自動設定」を追加。起動中プロセスと既定ポート（VOICEVOX 50021 / Ollama 11434 / Stable Diffusion WebUI 7860）と PATH 上の ffmpeg を走査し、`VOICEVOX_PATH` / `VOICEVOX_URL` / `OLLAMA_BASE_URL` / `SD_WEBUI_BASE_URL` / `FFMPEG_BIN` を検出して設定へ適用できるようにした（`core/service_detector.py`）。`OLLAMA_BASE_URL` を編集可能設定に追加。
- Trial 透かしを最終エンコードへ畳み込み、透かし専用の追加再エンコードパスを廃止（`core/native_renderer.py`）。透かし文字・サイズは `config/config.py` の `TRIAL_WATERMARK_*` で設定可能にした。
- バックアップ作成前に対象DBを `wal_checkpoint(TRUNCATE)` し、WALの取りこぼしを防止。復元時は対象DBの `-wal` / `-shm` を除去して古いWALの再生による破損を防ぐようにした（`web_app/services/backup_service.py`）。
- `JobManager._active_profile_id` の `except Exception` 握り潰しを `get_active_profile()`（未設定時 None）へ置き換え、想定外エラーを伝播させるようにした。
- 本番レンダー関数 `render_native_test` を実体に合わせて `render_native` へ改名。

### 製品版MVPの設定モード分離・テンプレートパックUI・診断強化を追加

- 設定画面に **通常 / 詳細 / 開発者** の表示モード切替を実装し、危険設定・開発者向けタブ（管理者設定など）を通常利用時は隠すようにした。選択はブラウザ `localStorage` に保持する純UI設定で、設定DBの正本にはしない。
- 設定画面「テンプレート」タブにテンプレートパックのインポート/エクスポートUIを追加した（既存の `/api/prompt-templates/export` `/import` を利用）。エクスポートはJSONダウンロード、インポートは確認ダイアログ + `confirmed=true` 必須。
- 診断パッケージの `environment.json` に nvidia-smi による GPU 診断を追加した（未検出時は状態として記録）。
- 初回セットアップ redirect を「active channel 未登録の初回起動時のみ」に限定した。active channel があればセットアップ未完了でも通常画面に入れ、生成・アップロードのみブロックする（従来は未完了で全画面が `/setup` へ誘導され、既存画面が利用できなかった）。

### ドキュメントを現行runner・DB正本仕様へ整理

- README / MANUAL / SPEC / AGENTS の旧仕様・重複説明を整理し、生成・レンダーは別プロセスの `workers.runner` が `metadata.db:jobs` を処理する運用へ統一した。
- SPEC のスキーマ版数を v7 に更新し、`jobs` の `profile_id` / `params_json` / `cancel_requested` / `heartbeat_at` / `runner_pid` を明記した。
- 旧 `.env` チャンネル設定例や古い尺推定値を削除し、チャンネル登録は `channel_profiles`、台本本文は `videos.script_content`、設定は `data/settings.db` 優先という現行仕様へ揃えた。

---

## 2026-06-02

### 履歴詳細の音声・背景件数を「生成済み / 期待数」表示に変更

- 履歴詳細の「音声データ」「背景画像数」を、生成済み数だけでなく `生成済み / 期待数`（例: `24 件 / 24 件`、`7 枚 / 8 枚`）で表示するようにした。期待数は保存済み台本（`videos.script_content`）から `workers.main` の生成ロジック（句読点分割によるWAV数・format依存の背景上限）を再利用して算出する。途中停止や背景生成失敗で不足している履歴が一目で分かる。台本未保存の履歴は分母を出せないため従来どおり件数のみ表示にフォールバックする。

### runner起動時に前回の未実行ジョブを自動実行しないよう変更

- runner は起動時に、前回セッションで `queued` のまま残っていた `generate` / `render` を `cancelled`（`起動時に破棄（前回の未実行ジョブ）`）へ破棄するようにした（`discard_pending_jobs`）。再起動だけで前回のキュー残りが勝手に走らなくなる。起動後に新規登録したジョブは通常どおり実行する。

### SDサイズモード（縮小生成）を廃止し、生成コールを image_size なしに固定

- nanobanana 縮小生成（SDサイズモード）を完全廃止した。`sd_size_mode` 引数・パラメータ、`NANOBANANA_SD_IMAGE_SIZE` / `NANOBANANA_FHD_IMAGE_SIZE` / `SD_SIZE_IMAGE_SCALE` / `WEB_DEFAULT_SD_SIZE_MODE` 各設定、UI の「高画質（FHD）生成」チェックボックスを削除した。
- 生成コール（`ImageConfig`）は `image_size` を送らず `aspect_ratio` のみに固定。保存時に最終解像度へリサイズするため出力解像度は変わらない。SD指定後に nanobanana の 503 が頻発していた事象への対応。
- Stable Diffusion WebUI 経路も常に最終解像度で生成するようにした（縮小→拡大を廃止）。

### 台本保存済みの途中停止履歴をリトライ可能に変更

- 生成パイプラインの `save_script_content()` は独立したDB接続で即時 `commit()` するため、後段の音声・画像・レンダーで失敗しても保存済み台本はロールバックされない。
- 履歴一覧で、MP4・サムネイル・音声・背景がまだ無い途中停止フォルダでも、`videos.script_content` が保存済みなら表示するようにした。履歴詳細から保存済み台本を元に再生成できる。

### 固定コメント候補の予約状態フィルターを修正

- 固定コメント候補で、ローカルDBの `publish_status` が `scheduled` / `reserved` のまま残っていても、YouTube側の現在状態が `public` なら候補に表示するようにした。
- 固定コメントページの候補ゼロ表示で、フィルターJSが空テーブルを参照しないようにした。

### 背景再利用時にサムネイルも再利用

- `reuse_backgrounds` が有効な再生成では、退避済み `thumbnails/*.png` も復元し、`thumbnail.png` が戻った場合はサムネイル生成をスキップするようにした。
- LongサムネA/B/Cなど `thumbnails/` 配下のPNGも合わせて復元する。

### runnerの失敗ログ重複を抑制

- 生成パイプラインが `❌` 付きエラーをすでにジョブログへ出している場合、runner の失敗判定で同じメッセージを再追加しないようにした。
- runner が受け取ったジョブ進捗・警告・エラーを `yj.runner` のデバッグログへもミラーするようにした。DBジョブログだけに残り、debug 側で追えない状態を解消した。
- 生成結果メッセージが空、または `Error` 始まりの場合も failed 扱いにし、空の場合は「原因不明」エラーとしてジョブログ・デバッグログへ出すようにした。
- `/logs` のジョブログ自動更新をキャッシュなし取得にし、テキスト選択中でもジョブ進捗は更新するようにした。更新失敗時は画面へエラーを出す。
- ジョブ履歴ゼロで `/logs` を開いた後に新規ジョブが登録された場合も、ポーリングでカードを追加できるようにした。

### 管理者設定タブと runner 並行数のUI変更を追加

- 設定画面に「管理者設定」タブを追加し、生成・レンダー同時実行数、各種タイムアウト、Web UI 表示名、ジョブ履歴保持件数、1ジョブのログ保持行数を通常設定から分離した。
- `JOB_MAX_CONCURRENT_WORKERS` を設定DBから runner が定期的に読み直すようにし、保存後の次のジョブ取得から同時実行数が反映されるようにした。
- runner の内部スレッド上限 `JOB_RUNNER_EXECUTOR_CAPACITY` を追加し、管理者設定の同時実行数上限として使うようにした。

### よみがな辞書をDB正本へ移行

- よみがな辞書・自動学習辞書・読み補正候補の JSON 管理を廃止し、`data/settings.db` の `reading_dictionary_entries` / `reading_candidates` を正本にした。
- 現在の辞書データを初期 seed としてコード化し、新規DB作成時に投入するようにした。既存DBでは既存データを尊重し、seed 済みマークだけ記録する。
- 設定画面のよみがな辞書を1画面に統合し、「すべて / 手動 / 自動学習」で種別フィルターできるようにした。手動辞書と自動学習辞書で同じ表記が重複した場合は手動を優先し、自動学習側を除外する。

### チェックジョブの誤中断とログ不足を修正

- runner の heartbeat stale 回収を `generate` / `render` かつ `runner_pid` を持つジョブだけに限定し、Web プロセス内で動く `check` ジョブが「runner停止により中断」と誤表示される問題を修正。
- Web 内軽量ジョブにも heartbeat 更新を追加し、長いチェック・アップロード等でも実行中状態が DB 上で古くならないようにした。
- 台本チェックの尺レビュー・ローカルチェック・Ollama・ChatGPT 各段階をジョブログとデバッグログへ出すようにし、どこで待っているか追えるようにした。

### 都市伝説チャンネルの説明文・タグをチャンネル別（ジャンル駆動）に

- `zundamon_kowai` の `channel_theme` / `default_hashtags` を都市伝説向けに設定（DB）。
- YouTube 説明文の SEO 文・タグ・ハッシュタグが**全チャンネルで食べ物固定**だった問題を修正。`core/youtube_metadata.py` を active profile の genre 設定（`config/prompt_profiles/genres/{genre}/profile.yaml` の `seo_sentence_*` / `default_tags`）駆動にした。設定があるチャンネル（都市伝説）はそれを使い、未設定のチャンネル（食べ物）は従来の挙動のまま（**食べ物チャンネルは無変更**）。
- これにより都市伝説チャンネルの説明文に食べ物 SEO 文・`#食べ物雑学`・食べ物タグが混入しなくなった。`normalize_tags` の食べ物向け除外リスト（`都市伝説`/`怖い話` を含む）はジャンル設定チャンネルには適用しない。
- 再生リストは従来どおり genre 駆動（`playlist_categories.md`）で、`zundamon_kowai` は都市伝説カテゴリ。

### 背景プロンプトの欠落・デバッグログ氾濫を修正

- 背景プロンプト `prompt_bg_XXXX.txt` を「生成/再利用」に関わらず**常に保存**するようにした。従来は実生成パスでしか書いておらず、背景再利用時に prompt ファイルが欠落 → 画像ページのプロンプトが空表示・個別再生成が失敗していた。
- `initialize_db()` を**プロセス内で DB パス毎に1回だけ**実行・ログするようにした。移行で多数のホット関数（runner ポーリング・ジョブ操作）が毎回 `initialize_db()` を呼び、`[SQLite] DB 起動` ログが毎操作ごとに氾濫していたのを解消（DDL/マイグレーション再実行も回避）。
- app_shutdown のユニットテストが実 DB のジョブ状態に依存していたため、`_get_running_jobs` をモックして隔離した（移行で `list_jobs` が DB 参照になったことへの追随）。

### runner のffmpeg孤児・キャンセル不能を修正／ジョブログ肥大を抑制

- job-runner 終了・再起動時に、子の ffmpeg がツリーから外れて**孤児プロセスとして残る**問題を修正。Web から runner を停止する際に、Windows は `taskkill /T`、POSIX は専用プロセスグループへの `killpg` でツリーごと終了する（runner は `start_new_session` で起動）。
- レンダー（`render_native_test`）が `cancel_event` を受け取り、**セグメント境界でキャンセルを検出**して `RenderCancelled` で中断するようにした。実行中の長い ffmpeg エンコード後（秒単位）で確実に停止する。runner はこれを cancelled として記録する。
- `append_job_logs` がフラッシュ毎に `logs_json` 全体を再シリアライズして肥大化（O(n²)）していたため、1ジョブのログ行を `JOB_LOG_MAX_ENTRIES`（既定3000）で上限化し、古い行から破棄するようにした。

### profile_context のスレッドローカル残留（要再起動バグ）を恒久修正

- `profile_context.__enter__` が active profile の上書きをスレッドローカルへ設定した直後に `get_profile()` で例外が出ると、`with` 本体に入らず `__exit__` も呼ばれないため上書きが**残留**していた。スレッドプール上のスレッドが誤プロファイルを参照し続け、履歴フォルダ未検出（「フォルダが見つかりません」）・音声件数0件などが**アプリ再起動まで直らない**原因になり得た。`__enter__` 失敗時に必ず復元するよう修正し、リーク不可をテストで保証。

### BGM パスを相対化・履歴からBGM編集を撤去・food_trivia 残骸を掃除

- `bgm_assets.file_path` をプロファイルルート相対（例 `000_assets/bgm/<id>.mp3`）で保存し、読み出し時に現プロファイルの絶対パスへ解決する方式へ変更。`output/` ディレクトリごと移動・プロファイル名変更しても壊れないようにした。既存の絶対パス行は初回に相対へ自動マイグレーションする。
- これにより、旧プロファイル名(food_trivia)の絶対パスが残っていた zunkami の既定BGMが正しく解決されるようになり、再レンダー時の「BGMファイルが見つかりません」を解消。
- `resolve_bgm_selection` に、実体が無い場合へ現プロファイルの `000_assets/bgm/` をファイル名で探す自己修復フォールバックを追加。
- 履歴詳細画面から BGM の表示行と編集UI（モード/ファイル/音量）を撤去。BGMはチャンネル設定で管理し、履歴からの再作成は常にチャンネル既定を使用する。
- 存在しないプロファイル（food_trivia / urban_legend）を参照する `channel_schedule_settings` / `prompt_templates` の孤立行を削除。

### 設定画面の起動時プリロードを追加

- Web UI 起動時に設定画面用の補助データ（Ollamaモデル一覧、`assets/bgm/` の音源ファイル一覧）をバックグラウンドで先読みするようにした。
- `/settings` のHTML生成時にフルサービス診断を待たず、APIキー登録状態はDBの bool だけで表示するようにした。
- プリロード未完了でも `/api/settings/ollama-models` / `/api/settings/bgm-files` は暫定値を即返し、設定項目本体が外部サービス待ちで出ない状態を避けるようにした。

### 履歴一覧の行ボタンを修正

- 履歴一覧の行ごとの「削除」「フォルダを開く」ボタンが、HTML属性内の引用符衝突で動かない場合があったため、行の `data-name` を読むイベントリスナー方式に変更した。

### ジョブログ表示を共通化

- 履歴詳細の処理ログとログ画面のジョブカード描画を `job_poll.js` の共通ロジックへ寄せた。
- job-runner 実行中の queued ジョブで、Webプロセス側の古いメモリ状態ではなく DB の最新ログを返すようにした。
- デバッグログタブも `WEB_LOG_POLL_INTERVAL_MS` と同じ間隔で自動更新するようにし、手動更新ボタンを削除した。

### 履歴一覧の途中データ除外

- 台本だけDB保存された途中停止データが履歴一覧へ出ないよう、render_info / MP4 / サムネ / 実生成ファイルがある履歴だけ表示するようにした。
- 履歴詳細のファイル状態に音声データ数を追加し、「フォルダを開く」が `videos/` / `000_uploaded/` 配下の実フォルダを開くよう修正した。

### Web薄化とjob-runnerを導入

- 生成・レンダージョブを Web プロセス内 subprocess IPC から、`metadata.db:jobs` を共有状態にした常駐 `workers.runner` 実行へ移行した。
- jobs に `profile_id` / `params_json` / `cancel_requested` / `heartbeat_at` / `runner_pid` を追加し、runner が `queued` を原子的に claim して実行するようにした。
- runner はジョブの `profile_id` をスレッドローカルで固定して実行し、Web UI でチャンネルを切り替えても生成先 profile が混線しないようにした。
- ジョブ詳細取得・キャンセル・ログ追記も `job.profile_id` 基準にし、ジョブ投入後にWeb UIのactive profileを切り替えても対象ジョブを取りこぼさないようにした。
- 既存DBの jobs テーブルに新列が無い状態でも、ジョブ参照・キャンセル・runner claim 前に migration を保証するようにした。
- 旧 `web_app/worker_runner.py` / `workers/worker_pipeline.py` / `workers/worker_render.py` と `input.json` / `result.json` ベースのファイルIPCを廃止した。
- デバッグログを `app_debug_web.log` / `app_debug_runner.log` に分離し、QueueListener 経由の書き込みで Windows のローテーション衝突を避けるようにした。

---

## 2026-06-01

### 依存漏れの追加・固定コメント候補の N+1 解消

- `requirements.txt` に不足していた依存を追加: `keyring`（macOS/Linux のシークレットマスターキー保管。Windows は DPAPI のため `platform_system != "Windows"` 限定）、`psd-tools`（キャラ立ち絵PSDの表情レイヤー読み込み）。これまで Mac/Linux で認証情報の保存・復号が動かない可能性があった。
- 固定コメント候補一覧 `list_fixed_comment_candidates` が候補フォルダ1件ごとにレコードを個別クエリしていた N+1 を、`_fixed_comment_records_bulk()` の1クエリにまとめて解消（履歴一覧と同方針）。

### 履歴一覧の N+1 クエリを解消

- 履歴一覧の生成でフォルダ1件ごとにメタ情報を個別クエリ（4テーブルJOIN）していた N+1 を、`_history_db_info_bulk()` で `WHERE local_id IN (...)` の1クエリにまとめて解消。動画本数が増えても `/history` 表示が重くならないようにした。回帰テストを追加。

### 画像の手動差し替えをコピペ対応

- 画像確認画面の手動差し替えに **「📋 貼り付け」ボタン**を追加し、クリップボードの画像で差し替えできるようにした（ファイル選択不要）。Clipboard API でワンクリック貼り付け、未対応/権限拒否時は対象を選んで Ctrl+V するフォールバックも用意。バックエンド（`/api/images/{name}/replace`）は変更なし。

### サムネ欠番の再生成・再生成経路のテスト追加

- 背景再利用時にサムネイル(`thumbnail.png`)が欠けている（503失敗など）と、再生成せず「サムネイル画像を生成できませんでした」で**中止**していたのを修正。再利用指定でもサムネが無ければ再生成するようにした（背景のファイル名基準修正と同系統）。
- `reuse_audio` / `reuse_backgrounds` が worker へ正しく渡るサービス層テスト、`/api/history/regenerate`（reuse_audio受理）・`/api/images/{name}/regenerate`（job_id返却）の経路テストを追加。

### 背景再利用のバグ修正（インデックス基準→ファイル名基準）

- `reuse_backgrounds` の再利用判定が並び順インデックス基準だったため、欠番（503失敗などで未生成の背景）があると背景番号がズレて誤った画像を割り当て、かつ**欠番自体を再生成しない**バグを修正。期待ファイル名 `bg_NNN_001.png` の存在で判定し、**有れば再利用・無ければ再生成**するようにした（生成と再利用で `_background_filename()` を共用）。
- これにより「履歴から再生成（背景再利用）で未生成分だけ作り直す」が全工程再生成パスでも正しく機能する。回帰テストを追加。

### コード整理（バッチ削除・音声孤児掃除・SDエラー分類・例外コメント）

- 到達不能な死にコードのバッチ背景生成経路（`use_batch_api` / `generate_backgrounds_batch`）を削除。完了タイムアウト無しのポーリングによるハングリスクも併せて解消。
- `reuse_audio` 時、台本変更で不要になった旧WAV（孤児）を `_cleanup_orphan_audio()` で掃除し、字幕数とWAV数の不一致を防止。
- Stable Diffusion WebUI 経路の背景生成失敗も `classify_image_api_error` で分類し `ImageGenerationError`（エラーコード付き）として扱うよう統一。
- サイレントに握りつぶしていた `except Exception: pass` 13箇所に `# フォールバック許可:` 理由コメントを付与（no-silent-fallback ルール準拠の明確化）。
- `_cleanup_orphan_audio` と SD WebUI エラーコードの単体テストを追加。

### 失敗背景の再生成導線・音声再利用・エラーコード全面適用

- 履歴詳細に「⚠ 背景生成の失敗」カード（背景番号 / エラーコード / HTTP / モデル）と **「失敗した背景だけ再生成」** ボタンを追加。`image_generation_failures`（DB）を参照し、保存済みプロンプトで該当背景のみ再生成、成功でその失敗記録を消す。
- 再生成時に既存音声を使い回す **「音声を再利用する」**（`reuse_audio`、既定OFF）を追加。バックアップの WAV を復元し、同じ台本でファイル名が一致する音声は VOICEVOX 合成をスキップする。
- エラーコードを画像生成以外にも適用: `E-SECRET-MISSING`（APIキー未登録）/ `E-SCRIPT-MISSING`（台本なし）/ `E-VOICE-FAIL`（音声失敗）/ `E-RENDER-FAIL`（レンダー失敗）を該当例外・メッセージに付与。

### エラーコードの中央管理とデバッグログ拡充

- エラーコードと文言を `core/error_codes.py` の `ERROR_CATALOG` で一元管理するようにした（`E-IMG-BUSY` / `E-IMG-AUTH` / `E-IMG-QUOTA` / `E-IMG-FAIL` / `E-SECRET-MISSING` / `E-SCRIPT-MISSING` / `E-VOICE-FAIL` / `E-RENDER-FAIL` / `E-UNKNOWN`）。`format_error()` / `AppError` / `image_error_code()` を追加。背景生成失敗ログ・`image_generation_failures.error_code`（スキーマ v7）にコードを付与する。
- `app_debug.log` を拡充: 全ジョブのログ（ワーカー subprocess の stdout/stderr 転送分を含む）を `job_manager._log()` から `yj.job` ロガー経由でミラーし、生成・レンダーの進捗とエラーが永続デバッグログにも残るようにした。ジョブ開始/終了/所要時間、ワーカー起動/終了 exit code、結果ファイル無しクラッシュも記録。ログ書式に関数名:行番号を追加。

### 画像生成API 503混雑のエラー表示・再実行導線を改善

- 背景画像生成（Gemini / Nano Banana）の失敗を HTTP ステータスで分類するようにした（`401/403`=認証・権限、`429`=レート制限・クォータ、`503`=API混雑、その他=通常）。`core/image_generator.py` に `ImageGenerationError` / `classify_image_api_error()` を追加。
- **503 は「🚧 画像生成API混雑 / 後で再実行推奨」**と通常エラーと分けて目立つ形で表示し、失敗ログに 動画タイトル / 背景番号(例 4/8) / モデル / HTTPステータス / エラーメッセージ / 既存背景の再利用可否 を出すようにした。1本でも 503 があれば「台本やプロンプトの問題ではない」旨を明示する。
- **自動フォールバック禁止**を維持（別モデル・別バックエンド・ローカル生成へ切り替えない）。生成済み背景は破棄せず、再生成時は『背景再利用』で未生成分だけ作り直せる。
- 失敗記録を `metadata.db` の `image_generation_failures` テーブル（スキーマ v6）に保存するようにした（`_meta/*.json` は作らない）。背景生成開始時に旧記録をクリアする。

### ログ画面のコピペ改善（更新間隔を長く・選択中は再描画停止）

- `/logs` の自動更新間隔を固定2秒から `WEB_LOG_POLL_INTERVAL_MS`（既定8秒）に変更し、設定画面からも調整可能にした。
- ログをテキスト選択している間は、その回のポーリング再描画をスキップしてコピー操作が途切れないようにした。

### Ollama冒頭レビューの可視化を改善

- Ollama冒頭レビュー完了時に、`overall_score` と hook / title_match / tempo / clarity / loop / cta の詳細スコア、`must_fix`、`warnings`、`fix_target` をGUIログへ出すようにした。
- 70〜79点で `must_fix` が空の場合は「生成継続可 / 軽微改善推奨」「中止不要。冒頭改善余地あり」と表示し、停止対象ではないことを分かるようにした。
- 78点付近への採点癖を検証できるよう、Ollama の `model` / `prompt_version` / `raw_response` / パース後スコア / サブスコア / 警告文 / `fix_target` / `created_at` を `metadata.db` の `script_quality.opening_review_debug`（JSON、スキーマ v5）へ保存するようにした（`get_opening_review_debug` で取得）。ローカルJSONファイルは作成しない。
- Ollamaレビューのプロンプトに、80〜89点と70〜79点の使い分け、78点時の具体的修正例必須、抽象的な「引きが弱い」だけの禁止を明記した。

### 生成ログの解像度表記を整理

- 解像度ログを「縮小生成解像度(SD) → 最終保存解像度(FHD)」の矢印表記に変更した。SD（縮小生成）は `540x960 (SD) → 1080x1920 (FHD)`、FHD（高画質生成）は `1920x1080 (FHD)` のように表示し、フルHD解像度に `(SD)` が付いて紛らわしかった旧表記を解消した。
- Nano Banana の送信設定ログも同じ矢印表記に統一し、`1K` / `2K` のAPI指定ラベルは前面に出さない。

### LLM/尺チェック表示と個別履歴削除を修正

- `/check` は推定尺を基本表示とし、Ollama / ChatGPT が有効な場合だけ各スコアを追加表示するようにした。無効な LLM は呼び出さず、ローカルレビュー詳細や修正依頼文は表示しない。
- 履歴一覧・履歴詳細の個別削除で、APIエラー時に画面上へ必ず原因を表示するようにした。
- `SPEC.md` に残っていた作業者向け運用ルールを `AGENTS.md` へ移し、仕様書の先頭表現を複数チャンネル共通へ整理した。
- 説明欄フッターのチャンネル登録URLとハッシュタグを active profile から組み立てるようにし、特定チャンネル固定の文言が別チャンネルへ混ざらないようにした。

### 投稿予約スロットをチャンネル別設定化

- Shorts の既定予約スロットを 07:00 / 12:00 / 21:00、Long の既定予約スロットを 22:00 に変更。タイムゾーンは Asia/Tokyo。
- Long の土日 12:00 追加枠と旧 21:00 枠を廃止し、曜日問わず 22:00 のみに統一した。
- `data/settings.db` に `channel_schedule_settings` を追加し、食べ物雑学チャンネル・都市伝説チャンネル・今後追加されるチャンネルの投稿予約スロットを profile_id ごとに管理するようにした。
- 設定画面のチャンネル詳細フォームから、Shorts / Long の投稿予約スロットとタイムゾーンを編集できるようにした。
- 新規予約・公開予定変更候補・スロット詰め直しは active profile のチャンネル別スケジュール設定を使う。既存の予約済み `publish_at` は通常の設定変更では変更せず、詰め直し適用時のみ新スロットに従って更新される。

### 履歴削除・prefix正規化・台本先行保存を追加

- 履歴画面と履歴詳細から、確認付きで履歴フォルダと `metadata.db` の関連レコードを削除できるようにした。
- 旧 `short_` / `shorts_` / `long_` / `meeting_` 系のフォルダ名を読み取り時に後方互換として扱い、新規生成では設定済みの `Shorts_` / `Long_` / `ネタ会議_` 系へ正規化するようにした。
- 生成パイプライン開始直後に台本本文を `videos.script_content` へ保存するようにし、途中失敗時も台本が DB に残るようにした。
- 背景画像の「前と同じ」「再利用」指定を生成枚数から除外し、Nano Banana の不要な追加生成を防ぐようにした。Stable Diffusion WebUI 背景生成は直列化し、WebUI 側の詰まりを避けるようにした。
- 既存の profile 別 `metadata.db` で旧 `output_root` や移動前フォルダを指していた `videos.output_dir` を、実在する `output/{profile_id}/...` 配下へ補正した。

### 複数同時実行でWebが無応答になる問題をジョブ直列化（キュー）で解消

- 複数ジョブ同時実行時に Web プロセスが応答不能になり UI のログ更新が止まる事象を修正。`worker_runner.py` で `threading.BoundedSemaphore` によりワーカー subprocess を **直列実行（同時1本、`JOB_MAX_CONCURRENT_WORKERS` 既定1）** にし、超過分は順番待ち（キュー）にした。
- 設定値は `.env` ではなく `config/config.py` に置く。追加インフラ不要・純Python実装（配布・販売を想定し外部ミドルウェア＝Kafka/Redis 等に依存しない）。

### 履歴詳細の「メタデータ」欄を DB から再構築して復活

- `_meta/metadata.txt` 廃止（metadata.db 正本化）の際に履歴詳細の「メタデータ」欄が空（`metadata_txt=""`）になっていた回帰を修正。`video_metadata`（動画タイトル・サムネ文字・説明文・タグ・生成区分・元動画・目的・固定コメント）から旧 `metadata.txt` と同じ体裁で再構築するようにした。

### 台本ファイル(script.txt)を完全廃止し metadata.db を唯一の正本に

- 生成パイプラインが `script.txt` を**出力しない**ようにし、台本本文を `sync_folder_to_db(theme_dir, script_content=...)` で `metadata.db` の `videos.script_content` へ直接保存するようにした。
- 台本を読む全経路を DB 参照へ統一した: native レンダー（`native_renderer`）・アップロードのタグ抽出（`youtube_uploader`）・履歴詳細表示・画像の Shorts 判定・ネタ募集CTA候補カウント（`cta_policy`）・サムネイル再生成。`native_renderer` の字幕/演出/サイズ判定ヘルパーはファイルパスではなく台本テキストを受け取るように変更した。
- 既存フォルダの取り込み（`import_output_dir` / `sync_folder_to_db` の引数省略時）に限り、後方互換として既存の `script.txt` を読む。
- 不要になった `history_service._read_text` / `cta_policy._script_meta_from_path` を削除した。

### 履歴フォルダ参照先ズレ・再生成エラーを修正

- 履歴からの再生成が `metadata.db` の `videos.script_content`（正本）を読むようにした。従来はディスクの `script.txt` を読んでおり、DB の `output_dir` が旧パスのままだと参照先が外れて「再生成可能なscript.txtが見つかりません」になっていた。
- 履歴フォルダ名から実体パスを引く処理を `security.find_history_dir()`（`videos/` → `000_uploaded/` の順で解決）に統一した。画像配信（サムネイル・背景の表示）・画像再生成・手動差し替え・再レンダーが `videos/` 配下のフォルダを解決できず壊れていた不具合を修正。
- `upsert_video()` が `ON CONFLICT` 時に `videos.output_dir` を同期フォルダの実体パスへ更新するようにし、旧パスが残り続けないようにした。既存DBの古い `output_dir` は再同期で修正済み。
- `import_output_dir` の進捗 `print()` が絵文字で Windows(cp932) コンソールでは `UnicodeEncodeError` で落ちていたのを ASCII 表記に修正した。
- 履歴詳細の再生成フォームの文言・確認ダイアログ・エラーメッセージから `script.txt` 表記を外し、「保存済みの台本（DB正本）」を元に再生成する旨へ統一した。

### チャンネル識別子をハンドル基準に統一

- `profile_id` / `genre_profile` / `output_root` をチャンネルハンドル（`@` なし）へ統一するようにした。
- 既存 DB の異なる値はハンドル名へ移行し、関連テーブル・output フォルダ・genre_profile フォルダも合わせて移行するようにした。
- 旧 `default` に保存されていた APIキー・YouTube Client Secrets は、未登録の各チャンネルへ暗号化済みのままコピーするようにした。
- チャンネル詳細フォームから、そのチャンネル専用の APIキー・YouTube Client Secrets を登録できるようにした。

### APIキーのチャンネル別管理を復旧

- `GOOGLE_API_KEY` / `OPENAI_API_KEY` / `HF_TOKEN` の保存・状態表示・利用を active profile 基準に統一した。
- チャンネル切替時に設定ステータスキャッシュを破棄し、切替先 profile の認証状態を表示するようにした。
- profile 別の APIキー登録状態が混ざらないことをテストで確認するようにした。

### 画像手動差し替えとBGM選択を追加

- `/images` から背景画像・サムネイルを手動アップロードで差し替え可能にした。元画像は `000_backups/image_replacements/` に保存し、差し替え履歴は `metadata.db` の `image_replacements` テーブルに記録する。
- 設定画面にBGM管理タブを追加し、チャンネル別に `bgm_assets` を DB 管理できるようにした。生成・履歴詳細のレンダーでは「チャンネル既定 / 個別指定 / BGMなし」を選択できる。
- nativeレンダー時に選択したBGM情報を `render_info` に保存し、再レンダーやアップロード前確認で参照できるようにした。

### 固定コメント自動投稿の全チャンネル対応

- `AUTO_FIXED_COMMENT_PROFILE_SCOPE` を追加し、固定コメント自動投稿の対象を `all`（全チャンネル）/ `active`（アクティブのみ）で切り替え可能にした。
- `all` では登録済み channel profile すべての `metadata.db` と profile_id 別 YouTube OAuth token を使って未投稿候補を巡回する。
- 手動画面は従来通り active profile のみを対象にする。

### 現行ドキュメントの整理

- 現行アーキテクチャに関係する変更だけを記録する方針へ変更。
- `AGENTS.md` / `SPEC.md` / `README.md` / `MANUAL.md` / `CHANGELOG.md` の最新内容を正本として扱う運用に整理。
- 認証状態表示を DB の `encrypted_secrets` 基準に統一。

### YouTube側を正とする動画DB同期を追加

- `core/metadata_db.py` に `sync_youtube_statuses()` / `sync_youtube_statuses_from_api()` を追加。
- YouTube Data API の `title` / `privacyStatus` / `publishAt` / `publishedAt` / 動画種別を正として、`videos` / `render_info` / `youtube_status` を更新するようにした。
- YouTube側で削除済みの既知動画IDは、`delete_missing=True` 指定時に関連DBレコードも削除する。
- 同期後に孤立行を削除し、過去削除や移行で残った空欄メタデータが画面・集計に混ざらないようにした。
- スケジュール同期でも `metadata.db` へ YouTube 側の状態を書き戻すよう変更。
- 固定コメント、履歴表示、Analytics補助情報、CTAポリシー、YouTubeメタ、生成メタの参照・保存を `metadata.db` 正本へ寄せた。

### prompt_templates DB化

- `data/settings.db` に `prompt_templates` テーブルを新設。テンプレートを `profile_id` 単位で管理。
- `config/prompt_profiles/genres/{genre_profile}/` の既存ファイルから初期 seed を自動実行するようにした。
- `build_script_generation_prompt()` / `build_title_prompt()` / `build_meeting_script_prompt()` / `build_gemini_system_prompt()` が DB テンプレートから読み込むよう変更。
- テンプレート未登録時は `RuntimeError` で停止する。
- 設定画面に「テンプレート」タブを追加。active チャンネルのテンプレートのみ表示・編集可能。
- REST API として `GET/POST/PUT/DELETE /api/prompt-templates`、クローン、デフォルト設定、seed 実行を追加。

### 複数チャンネルプロファイル運用

- `channel_profiles` テーブルを `data/settings.db` に追加し、active profile によって出力パス・DB・プロンプトが切り替わる設計を導入。
- `core/channel_profile.py` を追加し、profile CRUD と `require_active_profile()` を提供。
- `config/prompt_profiles/genres/food_trivia/` と `genres/urban_legend/` を追加。
- `core/prompt_profile_loader.py` を追加し、seed 用プロンプトファイルを読み込む処理を集約。
- `core/script_prompts.py` からジャンル固有文言を除去し、`genre_profile` パラメータで切り替え可能にした。
- `core/output_paths.py` を profile 別パス解決の関数群に整理。
- `core/metadata_db.py` の DB パスを active profile の `000_data/metadata.db` に変更。
- Web UI ヘッダーに active channel profile を表示し、Web UI上で登録済み profile を切り替えられるようにした。

### ドキュメント整合

- `AGENTS.md` の出力フォルダ構造を `output/{profile_id}/videos/{テーマ名}/` 配下の現行仕様に更新。
- `AGENTS.md` に「Web UI チャンネル切替」セクションを追加。
- `AGENTS.md`・`SPEC.md` のプロジェクト概要を複数チャンネル対応の汎用ツールとして再記述。
- `SPEC.md` の Shorts アップロードスロットを 7:00 / 12:00 / 19:00 に修正。

---

## 変更履歴に書く目安

- プロンプト方針を大きく変えた。
- YouTube Analytics、アップロード、スケジュールなど運用フローを変えた。
- 生成物の品質レビュー、尺チェック、NGワードなど判定基準を変えた。
- Web UI の主要ボタンや出力形式を変えた。
