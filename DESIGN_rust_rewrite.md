# PicoCast 全面 Rust 作り直し設計

最終更新: 2026-10-16
利用者決定（2026-10-15）: **画面の外枠も動画生成の中身も、PicoAgent と同じく全部 Rust で作り直す。** 販売・配布はしない。目標は製品レベルの品質（`DESIGN_quality.md`）。
実装は Codex。この文書は設計のみ。進捗と決定待ちは `HANDOFF.md`。

この決定で、既存の設計書の扱いは次のように変わる。

| 文書 | 扱い |
|---|---|
| `DESIGN_quality.md` | **品質の目標と受入基準の正本**。Q1〜Q5・R1〜R6・UXの中身をRust版で実装する。開発検査は同書§5、着手順は実装計画§5を参照する |
| `DESIGN_foundations.md` | **考え方（唯一の持ち主＋ガード）は継続**。実装手段は本書 §6（clippy の禁止設定＋走査ガード）に置き換える |
| `DESIGN_picocast_v3.md` | 画面構成・データモデル・パイプライン・QAゲート・グロースエンジンの**中身は継続**。構成は本書§3のRust＋Tauri＋素のJSに統一する |
| `DESIGN_product_v2.md` | 個別タスクの仕様のうち、続行するもの（`DESIGN_quality.md` §0）は Rust 版の各クレートの要件として使う。Python へ実装するタスクは原則中止（§11） |

---

## 1. なぜ全部 Rust か（判断の根拠を残す）

- **PicoAgent と同じ技術・同じ規則・同じ部品**で、2 つのアプリの知見を相互に使える（プロセス管理・HTTP・保存・ガード・画面検査・スキル）。
- **型で壊れにくくなる**: データモデル（Project / Scene / Line）、エラーコード、設定、API の入出力が型で固定され、今の「文字列の辞書を受け渡す」箇所の取り違えがコンパイル時に止まる。
- **速度とメモリ**: 字幕・サムネの描画、画像処理、音声の解析をプロセス内で行え、外部プロセスの起動回数を減らせる。
- **ローカル HTTP サーバーが不要になる**: 画面とエンジンは Tauri の呼び出し（IPC）でつながるため、`127.0.0.1` で待ち受ける API（v2 T29 で保護が必要だったもの）自体が無くなる。

代わりに引き受けるもの:

- 作業量が最大（今の Python は約 3 万行）。**段階的に機能を移し、今の Python 版を本番として動かし続けながら置き換える**（§9）。
- Python にしか無い部品の置き換え（§5）。

---

## 2. リポジトリとフォルダ

利用者決定（2026-10-15）: **新しいリポジトリは作らず、今のフォルダとリポジトリを改名して、その中で Rust 版を作る。**

| 対象 | 現在（改名済み） |
|---|---|
| ローカルのフォルダ | `C:\00_PG\22_PicoCast` |
| GitHub | `benybeny777/PicoCast`（originはSSH） |
| VS Code のワークスペース | `PicoCast.code-workspace` |

### 2.1 中の配置

利用者決定（2026-10-16）: 保管用の `legacy/` は作らない。Rust版とPython旧版は切り替えまでリポジトリ直下で共存する。R5の切り替え検証後に不要な旧コードを削除し、必要ならGit履歴から参照する。Git管理外のDB・生成物・認証情報をコードと一緒に削除しない。

```text
22_PicoCast/
├─ AGENTS.md / CLAUDE.md / HANDOFF.md / SPEC.md / DESIGN_*.md / docs/
├─ .agents/skills/ / .claude/skills/
├─ Cargo.toml / crates/ / xtask/                 ← Rust共通基盤（実装済み）
├─ src-tauri/ / ui/                             ← Rust版の画面（未実装）
├─ core/ / web_app/ / workers/ / config/ / tests/ ← 現位置のPython旧版
├─ assets/ / scripts/ / dev/ / tools/            ← 旧版・開発用資産。棚卸しして移す
├─ start.ps1 / start.command / pyproject.toml / uv.lock / .python-version
└─ data/ / output/ / .venv/                      ← Git管理外。現位置を維持
```

- 起動手順は切り替えまで直下の `README.md` で扱う。
- 取り込み用コマンド名 `import-legacy` は旧版データを意味し、フォルダ作成を意味しない。

### 2.2 改名後の作業手順

フォルダ・GitHub・ワークスペースの改名は完了しているため繰り返さない。Claude Remote Controlの起動先も新パスへ更新済み。Codexの現在のチャットは新パスを参照しているが、アプリの保存済みプロジェクト登録は別に確認する。

1. `DESIGN_implementation_plan.md` §5の最初の未完了WPと、`HANDOFF.md` の現在状態を照合する。
2. Python 3.12への切り替え（WP-R0-2）は、自動運用と予約投稿の無い時間帯に現位置で行う。ジョブ表示だけでなく実プロセスも確認する。
3. 切り替え直前に設定・metadata DBをオンラインバックアップし、マスターキー・認証情報・未コミット差分をリポジトリ外へ退避する。
4. §12.4に従って環境を切り替え、最後に全テストとサンプル生成・レンダーをまとめて確認する。有料APIは明示指示または運用上の明確な必要がある場合だけ使う。
5. 検証が成功するまで旧環境を保持し、失敗時は環境を戻す。成功後に不要な旧環境を片付ける。履歴のジョブを勝手に削除・再実行しない。

---

## 3. 構成

```
22_PicoCast/（リポジトリ PicoCast）
├─ Cargo.toml                 ワークスペース
├─ crates/
│  ├─ picocast-core           ドメイン型（Channel / Project / Scene / Line / Asset / Job / Policy / Insight）、
│  │                          時刻（clock）、エラーコード（AppError）、設定レジストリ、ID、文言キー
│  ├─ picocast-store          SQLite（rusqlite）、マイグレーション、リポジトリ、自動バックアップ、整合性検査、
│  │                          秘密値の暗号化保存（DPAPI / キーチェーン＋AES-GCM）、旧データの取り込み
│  ├─ picocast-media          ffmpeg 実行、音声ミックス（ダッキング・ラウドネス）、字幕の組版（文節分割＋実測）、
│  │                          画像処理、キャラクター合成（レイヤー PNG）、サムネ描画、タイムライン合成、レンダー
│  ├─ picocast-voice          音声合成プロバイダ（VOICEVOX / AivisSpeech / COEIROINK / AquesTalk 系）、
│  │                          読みの正規化（Sudachi の Rust 版＋自前辞書）
│  ├─ picocast-ai             LLM・画像生成プロバイダ（Gemini / OpenAI / Claude / Ollama / Stable Diffusion WebUI）、
│  │                          共通再試行、費用台帳、結果キャッシュ、モデル一覧の検証
│  ├─ picocast-youtube        OAuth（ループバック方式）、再開可能アップロード、メタデータ・言語別ローカライズ、
│  │                          字幕、再生リスト、固定コメント、Analytics、クォータ台帳
│  ├─ picocast-pipeline       工程の DAG と成果物キャッシュ、永続ジョブ、事前点検、QA ゲート、
│  │                          自動運用のスケジューラ、スリープ抑止
│  └─ picocast-growth         分析スコア、勝ちパターン（Insight）、ネタ在庫、企画提案
├─ src-tauri/                 アプリ本体: Tauri の呼び出し口（commands）、トレイ、通知、単一起動、
│                             OS タスク登録と `--tick`（画面なしで 1 工程進めて終了）、外部サービスの起動管理
├─ ui/                        画面（PicoAgent と同じく素の ES モジュールの JS。ビルド工程なし）
├─ xtask/                     開発タスク: verify（整形・clippy・テスト・ガード・JS テスト）、旧データ取り込み、
│                             ゴールデンテストの基準更新
├─ tools/                     画面撮影・検査（PicoAgent の tools/screenshots 方式）
└─ docs/                      設計の決定記録（ADR）、利用者向けマニュアル
```

- **依存の向き**はクレートの依存関係で強制される（`core` ← `store`/`media`/`voice`/`ai`/`youtube` ← `pipeline`/`growth` ← `src-tauri`）。`core` が上位を参照するとビルドできない。今の Python の「逆向きの依存」（`DESIGN_foundations.md` G15）は構造上起きなくなる。
- 非同期は `tokio`。重い処理（レンダー・画像処理）は専用のワーカースレッドで行い、画面の応答を止めない。
- 画面は PicoAgent に合わせて素の JS（ES モジュール）。型の取り違えは、Rust 側の呼び出し口の型から生成した JSDoc 型定義と `node --test` の契約テストで防ぐ。

---

## 4. データ（`picocast-store`）

- **1 つの SQLite**（`%APPDATA%\PicoCast\picocast.db`、WAL）。`DESIGN_picocast_v3.md` §4 のモデルをそのまま使う。全テーブルに `channel_id`。
- **素材は内容アドレス**（`assets/ab/cd/<sha256>.<ext>`）。完成動画とサムネは `exports/<チャンネル>/` に分かりやすい名前で書き出す。
- 保存先は開発版（`PicoCast-Dev`）と通常版（`PicoCast`）で分ける（PicoAgent の規則）。他の場所を探さない。
- 日時は UTC の ISO 8601（`...Z`）だけを保存（`DESIGN_foundations.md` G1）。
- マイグレーションは番号付きで、適用前に自動バックアップ。破損を検出したら起動を止めて復元画面を出す（空で作り直さない）。
- 秘密値（API キー・OAuth トークン）は Windows では DPAPI で保護したマスターキー＋AES-GCM で暗号化して保存（今の Python 版と同じ方式。§9 の取り込みで復号できるよう、方式は `core/secret_store.py` の実装を読んで一致させる）。

---

## 5. Python 部品の置き換え表

| 今の Python 部品 | Rust での置き換え | 注意 |
|---|---|---|
| FastAPI＋Jinja の Web UI | Tauri＋素の JS 画面、Tauri の呼び出し（IPC） | ローカル HTTP サーバーは作らない |
| `sqlite3` | `rusqlite`（同梱ビルド） | |
| `requests` / `httpx` / `urllib` | `reqwest`（rustls）。共通の HTTP 部品 1 か所 | PicoAgent の `tools::http` と同じ考え方 |
| `google-genai` | Gemini の REST を `reqwest` で直接呼ぶ | 公式 Rust SDK は無い前提。モデル一覧の検証付き |
| `openai` | REST を直接呼ぶ | |
| `google-api-python-client`・`google-auth-oauthlib` | YouTube Data / Analytics の REST を直接呼ぶ。OAuth はループバック方式を自前実装（または `yup-oauth2`） | 利用者自身の client_secrets を使う方式は今と同じ |
| `sudachipy`＋`sudachidict_core` | `sudachi.rs`（Works Applications 公式の Rust 実装、Apache-2.0）＋同じ辞書 | 読みの結果が Python 版と一致するかを、自前辞書を含めて比較テストする |
| `psd-tools`（立ち絵 PSD の読み込み） | **取り込み時に一度だけ**レイヤーを PNG＋JSON へ書き出し、実行時は PNG を合成 | 実行時に PSD を解析しない。書き出しは移行ツール（Python 版を使ってよい）か Rust の PSD クレートで行う |
| `Pillow` | `image`・`tiny-skia`（描画）・`cosmic-text`（日本語の組版と文字幅の実測） | 字幕・サムネの文字は同じ組版部品で測って描く（`DESIGN_quality.md` Q2・Q4） |
| BudouX（予定していた文節改行） | `budoux-phf-rs`（Apache-2.0）か、モデル（JSON の重み）を読んで自前で判定 | 採用前にクレートの中身と保守状況を確認 |
| ffmpeg（外部） | 今と同じく外部の ffmpeg を共通のプロセス部品で実行。ラウドネスの測定は `ebur128` クレートも併用 | |
| `psutil`（サービス検出） | `sysinfo` | |
| `keyring` / DPAPI | Windows は `windows` クレートの DPAPI、macOS はキーチェーン（PicoAgent と同じ） | |
| `cryptography`（AES-GCM） | `aes-gcm` | |
| スレッド・ジョブ（`threading`・`job_manager`・`workers.runner`） | `tokio` のタスク＋DB の永続ジョブ（PicoAgent の `durable_jobs` と同じ考え方） | 別プロセスの runner を廃止 |
| 固定コメントの OS タスク（`--post-fixed-comments`） | 同じ exe の `--tick`（自動運用と共通） | |

---

## 6. 共通基盤とガード（Rust 版）

`DESIGN_foundations.md` の「唯一の持ち主＋ガード」を、Rust では次の2段で実現する。

1. **clippy の禁止設定**（`clippy.toml` の `disallowed-methods` / `disallowed-types` / `disallowed-macros`、理由付き）。持ち主のモジュールだけ `#[allow(clippy::disallowed_methods)]` を付ける。`cargo clippy -- -D warnings` で検出。
2. **走査ガード**（`xtask verify` 内。PicoAgent の `guard_scan` 方式）: clippy で表せない規則と、JS・設定ファイル・文書の規則を検査。clippy の設定ファイルの仕様が将来変わっても規則が抜けないよう、主要な禁止は走査ガードでも二重に検査する。

| 対象 | 持ち主 | 禁止するもの（持ち主以外） |
|---|---|---|
| 時刻 | `picocast_core::clock` | `chrono::Utc::now`・`Local::now`・`SystemTime::now`・`chrono_tz::Asia::Tokyo` などの直書き・`NaiveDateTime` の保存（JS: `new Date`・`Date.now`・`toLocale*` は `ui/app/time.js` だけ） |
| 外部プロセス | `picocast_core::proc`（タイムアウト必須・窓なし・ツリーごと終了） | `std::process::Command`・`tokio::process::Command` |
| HTTP | `picocast_core::http` | `reqwest::Client::new`・`reqwest::get` |
| DB | `picocast_store` | `rusqlite::Connection::open*` |
| ファイル書き込み | `picocast_core::fsutil`（原子的書き込み） | `std::fs::write`・`File::create`（大きい生成物は一時名→改名の専用関数） |
| 設定 | `picocast_core::settings`（型付きレジストリ。使う時点で読む） | `std::env::var`（許可リスト以外） |
| 出力 | `tracing`（構造化ログ。`job_id`・`channel_id` を必ず付ける） | `println!`・`eprintln!`・`dbg!` |
| 失敗 | `AppError`（エラーコード・対処） | 本番コードでの `unwrap`・`expect`・`panic!`（clippy の `unwrap_used` 等を deny。テストは許可） |
| AI・外部 API | `picocast_ai` / `picocast_youtube` のプロバイダ | 各社 API の URL の直書き（走査ガード） |
| 画面の文言 | `ui/i18n/*.json` | 画面コードへの日本語の直書き（新規は最初からカタログ） |

- `DESIGN_foundations.md` の G3（「今のチャンネル」）は、Rust 版では全関数が `ChannelId` を引数で受け取る設計にし、共通状態を持たない。
- 規則は AGENTS.md（Rust 版の節）に 1 行ずつ書く。

---

## 7. 品質の仕組み

- `xtask verify`: `cargo fmt --check` → `cargo clippy --all-targets -- -D warnings` → `cargo test` → 走査ガード → `node --test` → `cargo deny check`（脆弱性・ライセンス）。
- 検証はこのPCで `xtask verify` を実行する。GitHub Actionsは利用者指示（2026-10-16）により使用しない。ローカルで失敗を修正してから結果を記録する。
- 依存は `Cargo.lock` で固定。
- ゴールデンテスト（`DESIGN_quality.md` R6）: 固定の台本・素材・シードから作った動画の長さ・ラウドネス・字幕の位置・代表フレームの特徴量を基準と比較。基準の更新は `xtask golden --update` と理由の記録で行う。
- 画面: PicoAgent の撮影検査（Playwright）方式で、主要画面のはみ出し・重なり・状態表示を検査。

---

## 8. 画面（`ui/`）

`DESIGN_picocast_v3.md` §2 の構成（ホーム／つくる 3 ステップ／スタジオ／自動運用／ライブラリ／分析／設定）を、PicoAgent と同じ素の JS で作る。**見た目は `DESIGN_ui.md` と見本 `docs/design/picocast-ui-mockup.html` が正本**（トークン・部品・画面の配置）。ストアと購入関連は作らない（販売しないため）。

- 共通部品: 呼び出し（Tauri の `invoke` を包み、エラーコードと対処を表示）、時刻表示（`time.js`）、トースト、確認ダイアログ、ジョブ進捗、読み込み中・空・エラー状態。
- スタジオ: シーン一覧＋プレビュー（低解像度の即時レンダー）＋台詞・読み・表情・背景・BGM の編集＋その部分だけの再生成。
- デザイントークン（色・余白・文字）は `DESIGN_ui.md` §2。ライト／ダーク対応。部品の作り方（`ui/components/`）は PicoAgent と共通化できるものを共有する。

---

## 9. 移行（今の運用を止めずに置き換える）

### 9.1 進め方

1. **Python 版は凍結**: 新機能は入れない。本番の不具合修正と、実装計画 §8で定めた移行安全性のための変更だけを行う。既存PRのマージは別作業として扱う。
2. **Rust 版を並行で育てる**: 機能ごとに Rust 版を作り、Python 版と同じ入力で同じ結果になるかを比べる（下の「同等性の確認」）。
3. **影運用（シャドー）**: Rust 版を本番データのコピーで動かし、投稿だけはしない状態で 1〜2 週間、Python 版と並べて生成結果と QA の値を比べる。
4. **チャンネルごとに切り替え**: 1 チャンネルずつ Rust 版の投稿へ切り替える。運用元を1か所で管理し、旧版とRust版の二重投稿を拒否する（WP-R5-3・N30）。問題があれば切り替えを中止し、旧版に戻す。
5. **Python 版を片付ける**: 全チャンネルの切り替え検証後に、棚卸し表で不要と確認した旧コードを削除する。保管用フォルダや30日保管は設けない。Git履歴で参照できるコードと、Git管理外のDB・生成物・認証情報を分けて扱う。

### 9.2 旧データの取り込み（`xtask import-legacy`）

- 取り込み元: `data/settings.db`（設定・チャンネル・プロンプトテンプレート・キャラクター設定・読み辞書と候補・BGM・投稿スケジュール・自動運用・暗号化された秘密値）、各チャンネルの `metadata.db`（動画・台本・YouTube の状態・分析）、`output/` の素材。
- 秘密値は Python 版と同じ方式で復号して、Rust 版の方式で暗号化し直す。
- 立ち絵 PSD はレイヤー PNG＋JSON に書き出す（§5）。
- 取り込みは何度でもやり直せる（冪等）。取り込み元は読み取りだけで、書き換えない。
- 取り込み結果の照合: 件数・主要な値の一致を一覧で出し、不一致があれば止まる。

### 9.3 同等性の確認（機能ごとの完了条件）

| 機能 | 同等性の基準 |
|---|---|
| 読みの正規化 | 同じ台本から同じ読み（自前辞書を含む）。差分は一覧で確認し、意図した改善だけを認める |
| 音声 | VOICEVOX への要求パラメータが一致。末尾の無音（今の 0.5 秒付加の対処）を含む |
| 動画 | 同じ台本・素材で、尺が ±0.1 秒以内、字幕の数と表示時間が一致（字幕の改行は Q2 で改善するため差分を許容し、はみ出し 0 を条件にする） |
| 投稿 | 同じメタデータ（タイトル・説明・タグ・予約日時・再生リスト・申告）が作られる。影運用では API を呼ばず、要求内容だけを比較 |
| 分析 | 同じ期間で同じスコア・同じ横展開候補 |
| 自動運用 | 同じ方針で同じ工程・同じ本数の予定が作られる |

### 9.4 機能の棚卸し

着手前に、今の `SPEC.md` の全節と `web_app/routes/` の全 API を一覧にし、「移す・作り直す・やめる」を1件ずつ決めた表を作る（`docs/migration-inventory.md`）。漏れの防止のため、表に無い機能は移行完了と認めない。現時点で分かっている「やめる」候補: ライセンス・体験版・購入導線（販売しないため）、法務同意画面、更新確認、Web UI の多重起動対策（Tauri の単一起動で置き換え）。

---

## 10. マイルストーン（Rust 版）

| M | 内容 | 完了条件 |
|---|---|---|
| **R0 土台** | 改名後の文書整合・運用参照先の確認（§2.2）、ワークスペース、Python 3.12 と `uv.lock` の固定（§12）、ローカルの `xtask verify`、clippy の禁止設定と走査ガード、`core`（clock・AppError・settings・proc・http・fsutil・tracing）、`store`（DB・マイグレーション・バックアップ・秘密値）、AGENTS.md・HANDOFF・スキル | このPCで `xtask verify` が成功。ガードが「違反を入れると落ちる」ことをテストで確認 |
| **R1 取り込みと棚卸し** | `docs/migration-inventory.md`、`xtask import-legacy`、立ち絵の PNG 化 | 本番データのコピーを取り込み、照合が全件一致 |
| **R2 生成エンジン** | `voice`（VOICEVOX・読みの正規化）、`ai`（Gemini・Ollama・再試行・費用）、`media`（音声ミックス・字幕組版・キャラ合成・レンダー）、`pipeline`（工程キャッシュ・永続ジョブ・事前点検・QA ゲート） | §9.3 の読み・音声・動画の同等性。`DESIGN_quality.md` §1 の完成動画の指標 |
| **R3 YouTube** | アップロード・メタデータ・再生リスト・固定コメント・Analytics・クォータ | §9.3 の投稿・分析の同等性（影運用で要求内容を比較） |
| **R4 画面** | ホーム・つくる・スタジオ・自動運用・ライブラリ・分析・設定、トレイと通知、`--tick` の OS タスク | 主要画面の撮影検査が緑。Python 版の全操作が Rust 版でできる（棚卸し表で確認） |
| **R5 影運用と切り替え** | §9.1 の 3〜5 | 影運用 2 週間で重大な差分 0、チャンネルごとの切り替え完了、自動運用 30 日無人で `DESIGN_quality.md` §1 を満たす |
| **R6 伸ばす** | `growth`（勝ちパターン・ネタ在庫・企画提案）、多言語メタデータ・字幕、運用ダッシュボード | `DESIGN_quality.md` §1・§6および `DESIGN_implementation_plan.md` §5のR6完了条件 |

各マイルストーンの着手前に、その範囲の詳細設計（型・DB スキーマ・呼び出し口・画面の構成）を PR 本文に書く（利用者の承認は待たない。AGENTS.md）。`DESIGN_backlog.md` の優先度 A の案は、組み込み先のマイルストーンの詳細設計に ID 付きで取り込む。

---

## 11. 既存タスクの扱い（Python 側）

| タスク | 扱い |
|---|---|
| PR #35（自動運用） | 既存の未マージ作業。実装計画の各WPとは分けてレビュー・マージする |
| PR #36 の実装済み部分（ライセンス v1・v2、PicoAgent ルール・スキル） | マージしてよい。ライセンスは Rust 版では作らない（§9.4） |
| `DESIGN_product_v2.md` の未着手タスク（T5〜T41）、`DESIGN_foundations.md` の Python 版ガード、`DESIGN_quality.md` §5・§8 | **Python 版では実施しない**。中身は Rust 版の要件として R0〜R6 に取り込む |
| 移行の安全性 | WP-R0-2（環境固定）、WP-R1-7（テスト隔離・オラクル）、WP-R5-3（二重運用の拒否）は実施する（実装計画 §8） |
| 例外: 本番で実害が出ているもの | Python 版でも直す（AGENTS.md の「実害のあるバグは見つけ次第直す」）。例: 日付処理の不具合が実際に起きた場合 |

---

## 12. Python の扱い（CUDA を考慮した版の固定）

利用者決定（2026-10-15）: Python は CUDA の影響を考えた版に固定する。

### 12.1 Python が残る場所

Rust に作り直しても、次の 3 か所には Python が残る。

| 場所 | 用途 | CUDA |
|---|---|---|
| 旧アプリ（リポジトリ直下、凍結） | 移行完了まで本番を動かす。旧データの取り込み（§9.2）と立ち絵 PSD の書き出しにも使う | 使わない（エンコードは外部 ffmpeg の NVENC） |
| PicoCastが管理する機械学習ランタイム（将来の保留案） | 現行WPでは導入しない。ローカルAI作曲は作らない。将来別機能で採用する場合だけ§12.3の方針を再確認する | 現段階では導入しない |
| 利用者が別に入れた Stable Diffusion WebUI・Ollama | 画像生成・ローカル LLM | 各ソフトが自分で管理。**PicoCast は環境を共有しない・触らない** |

### 12.2 基準の版

- **Python 3.12 に固定する**（PicoAgent と同じ基準）。理由: PyTorch・CUDA 拡張（xformers・bitsandbytes など）の公式 wheel が揃っている版を優先し、最新の Python へ先行しない。PyTorch の最新安定版（2026-10 時点で 2.14 系）は Python 3.10 以上に対応しており、3.12 はどの CUDA 版の wheel でも揃っている。
- `requires-python = ">=3.12,<3.13"`。`.python-version` に `3.12` を置き、Python 本体は `uv` で取得した 3.12 系の最新パッチを使う。
- 依存はすべて `uv.lock` で版とハッシュまで固定する（今の `config/requirements.txt` は版の指定が 0 件）。

### 12.3 CUDA の選び方（機械学習ランタイム）

- 取得前に GPU を判定し、組み合わせを 1 つだけ選ぶ。

| GPU | 選ぶもの |
|---|---|
| NVIDIA・Turing（GeForce RTX 20 系）以降・ドライバが CUDA 13 に対応 | PyTorch の CUDA 13.0 版（PyPI の既定） |
| NVIDIA・Maxwell / Pascal、またはドライバが古い | CUDA 12.6 版（`download.pytorch.org` の `cu126`）。ドライバ更新で 13.0 にできる場合はその案内も出す |
| NVIDIA 以外・GPU なし | その機能が CPU を正式に支えている場合だけ CPU 版。支えていなければ機能を無効にし、理由を表示 |

- 選んだ組み合わせ（Python・PyTorch・CUDA・GPU 世代）を管理用のマニフェストに記録し、合わない環境の再利用を止める。1 つの機能に複数の CUDA 版を同時に入れない。
- Python 本体は 1 つだけ持ち、機能ごとに仮想環境だけを分ける（PicoAgent の規則）。古い本体・仮想環境・取得キャッシュは、新しい組み合わせの検証が成功したら同じ作業内で消す。
- 大容量（PyTorch＋モデルで数 GB〜十数 GB）のため、取得は利用者の明示操作のときだけ。容量と所要時間を事前に表示する。
- PyTorch と CUDA の具体的な版は、`uv.lock` と専用のインデックス指定（`cu130` / `cu126`）で固定する。版を上げるときは、全 CUDA 機能の公式 wheel が揃っていることを確認し、起動と実処理を新しい組み合わせで検証してから切り替える（毎月の依存監査スキルで点検）。

### 12.4 旧アプリ（現位置）の固定手順

旧アプリは今 Python 3.11.9 の仮想環境で動いている。凍結中も、取り込みツールと同じ基準にそろえる。**WP-R0-2で、改名済みのリポジトリ直下で行う。** フォルダやデータの移動は行わない。

1. `pyproject.toml`（`requires-python = ">=3.12,<3.13"`）と `.python-version`（`3.12`）を追加し、今の `config/requirements.txt` の実際の版（`pip freeze`）を元に `uv.lock` を作る。
2. 今の `.venv` を `.venv-311-backup` に退避してから、3.12 の `.venv` を作り直す。
3. 全テスト（`pytest -q`）と、サンプル台本 1 本の生成・レンダーで同等であることを確認する（SudachiPy・psd-tools・cryptography など C 拡張を含む部品の動作確認）。
4. 問題なければ退避した 3.11 環境を消す。問題があれば退避から戻し、原因を記録する。
5. `start.ps1`・`README.md` の起動手順を `uv` 前提に更新する。

- これは凍結中の Python 版で行う例外的な作業（環境の固定であり、機能追加ではない）。本番の自動運用が止まっている時間帯に行う。

### 12.5 出典（2026-10-15 時点）

- PyTorch 2.13 リリースブログ: https://pytorch.org/blog/pytorch-2-13-release-blog/
- PyPI の CUDA wheel を 13.0 へ移行（2.11）: https://dev-discuss.pytorch.org/t/transitioning-pypi-cuda-wheels-to-cuda-13-0-as-the-stable-release-2-11/3325
- PyTorch のリリース一覧: https://github.com/pytorch/pytorch/releases

## 13. 決定事項

| 項目 | 推奨 |
|---|---|
| リポジトリとフォルダ | **決定（2026-10-15）**: 今のものを改名して使う（§2） |
| ライセンス・購入導線を Rust 版で作らない | 作らない（販売しないため） |
| 画面を素の JS にする（PicoAgent と同じ） | する |
| 影運用の期間 | **決定（2026-10-15）**: 2 週間 |
| 旧コードの保管 | **決定（2026-10-16）**: 保管用フォルダと30日保管は撤回。切り替え検証後に不要コードを削除し、Git履歴で参照 |

## 14. 出典（ライブラリ調査 2026-10-15）

- sudachi.rs（Works Applications、Apache-2.0）: https://www.freshports.org/japanese/sudachi ・ https://pub.dev/packages/sudachi_dart
- budoux-phf-rs（Apache-2.0）: https://docs.rs/budoux-phf-rs
- clippy の設定（disallowed-methods 等）: https://doc.rust-lang.org/clippy/configuration.html
