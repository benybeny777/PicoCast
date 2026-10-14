# 共通基盤とガード設計（散らばった処理の一本化）

最終更新: 2026-10-15
位置づけ: `DESIGN_picocast_v3.md` §3 を支える横断設計。利用者決定（2026-10-15）「時刻は共通化したものだけで扱い、漏れが出ないようにする。同じように設計が微妙なところも直す」。
実装は Codex。この文書は設計のみ。進捗は `HANDOFF.md`。

---

## 1. 原則

横断的な処理（時刻・DB・外部プロセス・HTTP・設定など）は、次の3点を必ずセットにする。

1. **唯一の持ち主**: 1つの共通モジュールだけがその処理を直接行う。他は必ずそこを通す。
2. **ガードテスト**: 共通モジュール以外での直接使用をソース走査で検出し、テストを失敗させる。目視レビューに頼らない。
3. **規則の明文化**: AGENTS.md に「何を使い、何を使ってはいけないか」を1行で書く（ガードが入った時点で追記）。

PicoAgent の `mod guard` ＋ `crate::guard_scan` と同じ考え方。

### 1.1 ガードの共通仕組み（全ガードの土台）

- `tests/guards/scan.py`: 走査対象の唯一の列挙（`core/` `web_app/` `workers/` `tools/` の `.py`、`web_app/templates/*.html`、`web_app/static/*.js`。`tests/` と生成物は除外）。各ガードは対象を自前で決めず、ここから受け取る（走査漏れの防止）。
- Python は **AST で判定**する（文字列 grep はコメントや文字列中の誤検出が出るため）。JS / HTML は正規表現。
- `tests/guards/baseline.json`: 移行途中の既存違反の一覧（ガード名 → ファイル → 件数）。
  - 新しい違反（一覧に無い、または件数が増えた）→ 失敗。
  - 一覧にあるのに違反が減った → 失敗（一覧の更新を強制。**件数は減る方向にしか動かない「ラチェット」**）。
  - 一覧の更新は `python -m tests.guards.update_baseline` だけで行い、手で増やさない。PR 本文に増減を書く。
- 恒久的な例外は `tests/guards/allowlist.py` に「ファイル・理由・期限（任意）」付きで書く。理由の無い例外は失敗。
- 各ガードには「違反を含む小さなサンプルで本当に失敗する」ことを確かめるテストを付ける（ガード自体の穴を防ぐ）。

---

## 2. 一本化する対象（現状は 2026-10-15 に計測）

| # | 対象 | 現状（散らばり具合） | 持ち主（新設・統合） | 目標時期 |
|---|---|---|---|---|
| **G1** | **時刻** | `datetime.now/utcnow`・`date.today` 49か所（27ファイル）、`time.time()` 20、日本時間の決め打ち 51（15ファイル）、`fromisoformat/strptime` 28（12ファイル）、JS の `new Date`・`toLocale*` 7 | `core/clock.py`（Python）、`static/time.js`（画面） | **M0（最優先・違反ゼロまで）** |
| G2 | 設定値 | `config.py` が `os.environ.get` 235か所。各モジュールが `from config import 定数` で**読み込み時にコピー**（30か所・23ファイル）し、画面で変更すると `sys.modules` を全走査して書き換えている（`runtime_config.py:44`、`output_paths.py:218`） | `core/settings.py`（型付きの設定レジストリ） | M0 で骨組み、M2 で完了 |
| G3 | 「今のチャンネル」 | `profile_context` / `get_active_profile` / `require_active_profile` が 62か所（34ファイル）。暗黙の共通状態に依存しており、ジョブ・自動運用・OS タスクで取り違えの危険 | チャンネルを**引数で明示**（`channel_id`）。どうしても必要な所だけ `contextvars` | M2 |
| G4 | DB 接続 | `sqlite3.connect` 12か所（11ファイル）。WAL・待ち時間・外部キー・クローズの設定がばらばら | `core/db.py` | M0 |
| G5 | 外部プロセス | `subprocess.*` 30か所（16ファイル）、ffmpeg の直接組み立て 41か所（10ファイル）。タイムアウト・窓の非表示・強制終了の扱いがばらばら | `core/proc.py`、`core/ffmpeg.py` | M0 |
| G6 | HTTP | `urllib.request` / `requests` / `httpx` 38か所（13ファイル） | `core/http.py` | M0 |
| G7 | AI 呼び出し | Gemini クライアントの生成が2か所。再試行・費用記録・モデル選択・上限の確認を各所で行う必要がある | `core/providers/`（LLM・画像・音声・音楽の共通入口） | M0（再試行・費用）、M2（プロバイダ化） |
| G8 | ファイル書き込み | `write_text` / `open(..., "w")` 21か所。状態ファイルの書き込み途中で落ちると壊れる | `core/fsutil.py`（原子的な書き込み） | M0 |
| G9 | パス | `output_root` を使った自前のパス組み立て 94か所 | `core/paths.py`（保存先の全ルート）＋既存の `web_app/security.py`（利用者入力の検証） | M2 |
| G10 | エラーと例外 | `except Exception:` 107か所（ログ・再送出なしのものを含む）、`HTTPException(detail=str(e))` 10か所（内部の文言がそのまま画面へ） | `AppError` ＋ API の共通例外ハンドラ | M0（ガード導入）、M2（ゼロ） |
| G11 | ログ出力 | `print(` 51か所（8ファイル） | `logging`（CLI の利用者向け出力だけ `core/cli_output.py`） | M0 |
| G12 | バックグラウンド処理 | `threading.Thread(` 15か所（7ファイル）。例外が画面に届かず消える、終了時に回収されない | `core/background.py` | M0 |
| G13 | 画面の通信 | 生の `fetch(` 137か所。トークン付与（T29）・エラーコード表示・タイムアウトを各所で書く必要がある | `static/api.js` の `api()` | M0（T29 と同時） |
| G14 | 画面の文言 | テンプレートに日本語の直書き 1,472 行 | 文言カタログ（v2 T13 L3） | M3（新画面で最初からカタログ） |
| G15 | 依存の向き | `core` から `web_app` を読み込む逆向きの依存（`app_shutdown.py`、`service_detector.py`） | 層の規則（下の §4） | M0 |

---

## 3. 各基盤の仕様

### G1 時刻（`core/clock.py` / `static/time.js`）

**規則**

- 保存・通信・比較は**すべてタイムゾーン付きの UTC**。DB には ISO 8601 の `...Z` 形式だけを保存する。タイムゾーンなしの日時（naive）は受け付けず例外にする。
- 「日付」や「何時」のように人の暦で考える処理（投稿枠・1日の上限・日次集計）は、**必ずどのタイムゾーンの暦かを引数で渡す**。既定値で日本時間に寄せない。
- 画面に出す時刻の整形はサーバー側か `time.js` の1か所だけ。ブラウザの OS 設定ではなく、アプリ（またはチャンネル）のタイムゾーンを使う。

**API（Python）**

| 関数 | 用途 |
|---|---|
| `now() -> datetime` | 現在時刻（UTC・タイムゾーン付き）。唯一の「今」 |
| `monotonic() -> float` | 経過時間の計測専用（時刻としては使わない） |
| `app_tz() -> ZoneInfo` | アプリのタイムゾーン（設定 `APP_TIMEZONE`、既定は OS の設定。初回セットアップで確認） |
| `channel_tz(channel) -> ZoneInfo` | チャンネルのタイムゾーン（未設定なら `app_tz()`） |
| `local(dt, tz) -> datetime` | UTC → 指定タイムゾーンの表示用時刻 |
| `day_range(day: date, tz) -> (start_utc, end_utc)` | 暦の1日の範囲（日次上限・集計に使う） |
| `today(tz) -> date` | 指定タイムゾーンでの今日 |
| `at(day, hour, minute, tz) -> datetime(UTC)` | 「その日の何時」を UTC に（投稿枠） |
| `parse(text) -> datetime` | ISO 8601 を読み、タイムゾーン付き UTC で返す。タイムゾーンなしは `E-TIME-NAIVE` |
| `to_iso(dt) -> str` | DB・API 用の `...Z` 形式 |
| `youtube_quota_day()` | YouTube クォータの日付（太平洋時間で固定。仕様上の例外を1か所に閉じ込める） |
| `analytics_day_range(day)` | YouTube Analytics の日付境界（同上） |

- テスト用に `clock.freeze(dt)` / `clock.advance(td)` を用意し、各テストでの `local_now` のモンキーパッチ（`autopilot_store.local_now` など）を置き換える。既存の `autopilot_store.now_iso` / `local_now` は `clock` へ統合して削除する。

**ガード（`tests/guards/test_time.py`）**

- `clock.py` 以外で次を使ったら失敗: `datetime.now` / `datetime.utcnow` / `datetime.today` / `date.today` / `time.time` / `time.localtime` / `time.strftime` / `datetime.fromisoformat` / `datetime.strptime` / `timezone(timedelta(hours=...))` / `ZoneInfo("...")` の直書き / `pytz`。
- 文字列 `"Asia/Tokyo"`、`"JST"`、`hours=9` を `clock.py` 以外で使ったら失敗。
- JS: `new Date(`、`Date.now(`、`toLocale*` を `time.js` 以外で使ったら失敗。
- G1 は**ベースライン（移行途中の例外）を持たない**。M0 の中で一気に置き換えてゼロにする（利用者要望）。

**移行**

1. `clock.py` と `time.js` を作る。
2. 全使用箇所を置き換える（機械的に置き換えられるものと、暦の判断が要るものに分けて一覧化し、後者は1件ずつ「どのタイムゾーンの暦か」を決めて PR 本文に表で残す）。
3. **既存データの移行**: DB の日時列を棚卸しし（テーブル・列・現在の形式＝UTC か日本時間の naive か）、日本時間の naive は `+09:00` として解釈して UTC へ変換するマイグレーションを書く。移行前に自動バックアップ（v2 T21）。
4. ガードを有効化。
5. `APP_TIMEZONE` とチャンネル別タイムゾーンの設定画面。既存チャンネルは移行時に `Asia/Tokyo` を明示設定する（挙動を変えないため。暗黙の既定にはしない）。

### G2 設定（`core/settings.py`）

- 全設定を**1つのレジストリ**で定義する: キー・型・既定値・範囲・スコープ（アプリ / チャンネル）・管理者専用か・秘密値か・説明（文言カタログのキー）・再起動が必要か。
- 読み出しは**使う時点で** `settings.get("KEY", channel=...)`。モジュール読み込み時に値をコピーしない。これで `sys.modules` 全走査による反映（`runtime_config.py` / `output_paths.py`）を廃止できる。
- チャンネル別の上書きの解決（チャンネル値 → アプリ値 → 既定）はレジストリの中の1か所だけ。
- 設定画面（`EDITABLE_CONFIG`）・SPEC の設定一覧・診断 ZIP の伏せ字対象は、レジストリから**自動生成**（手で同期しない）。SPEC の表は生成結果と一致しているかをテストで確認。
- 環境変数は「起動フラグ」と「マスターキー」だけ。レジストリに `env_allowed=True` と理由を書いたものに限る。
- ガード: `from config import <定数>` と `config.<定数>` の読み出しを、`settings.py` 以外で禁止（ベースライン付きで M2 までにゼロ）。`os.environ` の参照を許可リスト以外で禁止。

### G3 チャンネルの明示（「今のチャンネル」をやめる）

- 処理は `channel_id` を引数で受け取る。API は URL やリクエスト本文に `channel_id` を含め、サーバー側で「画面で選択中のチャンネル」と照合する（今の `_check_profile` を一般化）。
- 「画面で選択中のチャンネル」は**画面の状態**であり、エンジン側の共通状態にしない。
- ジョブは登録時に `channel_id` を持ち、実行時にそれ以外を参照できない（DB アクセスは `db.for_channel(channel_id)` 経由）。
- ガード: `get_active_profile` / `require_active_profile` / `profile_context` を API 層の入口（ベースライン付き）以外で禁止。

### G4 DB（`core/db.py`）

- `connect(kind)` だけが `sqlite3.connect` を呼ぶ。毎回 `journal_mode=WAL`、`busy_timeout`、`foreign_keys=ON`、`row_factory` を設定する。
- `with db.tx() as cur:` で、トランザクションと確実なクローズを行う（GC 任せにしない）。
- スキーマ移行は番号付きのマイグレーション一覧で管理し、適用前に自動バックアップ（v2 T21）。v3 M2 の DB 統合もこの仕組みで行う。
- ガード: `sqlite3.connect` を `db.py` 以外で禁止。

### G5 外部プロセス（`core/proc.py` / `core/ffmpeg.py`）

- `proc.run(args, *, timeout, cancel=None, cwd=None, env=None)`: タイムアウト必須、Windows ではコンソール窓を出さない、タイムアウト・キャンセル時はプロセスツリーごと終了、ログには秘密値を伏せたコマンドを出す、終了コードが 0 以外なら `AppError`。
- `ffmpeg.py`: 実行ファイルの解決（設定値・自動導入先。他を探さない）、エンコーダ・プリセットの適用、進捗の取り出し、よく使うフィルタ（字幕・ダッキング・ラウドネス）の組み立てを1か所に。各所の ffmpeg 引数の組み立てを移す。
- ガード: `subprocess.*` / `os.system` / `os.popen` を `proc.py` 以外で禁止。`"ffmpeg"` の文字列と `FFMPEG_BIN` を `ffmpeg.py` 以外で禁止。

### G6 HTTP（`core/http.py`）

- 共通セッション（接続の再利用）、**タイムアウト必須**、User-Agent `PicoCast/<SemVer>`、再試行は明示的に指定した場合だけ（v2 T32 の共通再試行）、URL・ヘッダー内の鍵はログで伏せる、HTTP エラーを `AppError` に変換。
- ガード: `urllib.request` / `requests` / `httpx` / `http.client` を `http.py` 以外で禁止（Google の公式 SDK の内部通信は対象外）。

### G7 AI 呼び出し（`core/providers/`）

- 種類ごとの共通入口（`llm.generate()` / `image.generate()` / `tts.synthesize()` / `music.generate()`）。入口で「モデルの選択（設定から）→ 費用上限の確認（v2 T25）→ 呼び出し（共通再試行）→ 費用の記録 → 結果のキャッシュ」を必ず通す。
- 各社 SDK の使用は `providers/<社名>.py` の中だけ。
- ガード: `google.genai` / `openai` / `anthropic` などの SDK の読み込みを `providers/` 以外で禁止。

### G8 ファイル書き込み（`core/fsutil.py`）

- `write_atomic(path, data)`（一時ファイル → `fsync` → 置き換え）、`write_json_atomic`、壊れたファイルの退避 `quarantine(path)`。
- 状態・設定・台帳など「途中で壊れると困る」ファイルは必ずこれを使う。大きい生成物（動画・音声）は一時名で書いて完成時に名前を変える。
- ガード: `open(..., "w"/"wb"/"a")` と `Path.write_text` / `write_bytes` を `fsutil.py` と許可リスト以外で禁止（ベースライン付き）。

### G9 パス（`core/paths.py`）

- 保存先のルート（データ・素材・書き出し・ログ・バックアップ・ツール・一時）を1か所で定義（v2 T6 の分離もここ）。チャンネル別の場所は `paths.channel_dir(channel_id, kind)`。
- 利用者の入力から来るパスは従来どおり `web_app/security.py` で検証してから `paths` に渡す。
- ガード: `output_root` 属性の直接使用と `os.path.join(..., "output", ...)` を `paths.py` / `security.py` 以外で禁止（ベースライン付き）。

### G10 エラーと例外

- 利用者に見えるエラーはすべて `AppError(コード)`。API は共通の例外ハンドラが `{code, message, fix}` に変換し、内部の例外文字列を画面に出さない。
- `except Exception` は「ログ（`exc_info`）を残して再送出」「`AppError` に変換して送出」「`# フォールバック許可:` 付き」のいずれかだけ。
- ガード（AST）: `except` 節の本体に `raise` も `# フォールバック許可` も無いものを禁止（ベースライン付きで M2 までにゼロ）。`HTTPException(detail=str(...))` を禁止。

### G11 ログ（`logging`）

- `core` / `web_app` / `workers` での `print(` を禁止。OS タスクや CLI の利用者向け出力は `core/cli_output.py` に集約。秘密値の伏せ字はログの共通フィルタで行い、さらに呼び出し側でも値を渡さない（AGENTS.md）。

### G12 バックグラウンド処理（`core/background.py`）

- `background.start(name, fn)`: 名前付き、例外をログに残し、利用者に見える失敗なら通知（ホームの赤信号）に載せる。アプリ終了時の回収を登録（既存の `app_shutdown` と統合）。
- ガード: `threading.Thread(` を `background.py` 以外で禁止。

### G13 画面の通信（`static/api.js`）

- `api(method, path, body)`: トークンの付与（v2 T29）、JSON の解析、`{code, message, fix}` の表示、タイムアウト（`AbortController`）、二重送信の防止。
- ガード: 生の `fetch(` を `api.js` 以外で禁止（ベースライン付き。T29 と同時に置き換えると効率的）。

### G14 画面の文言

- 新しい画面（v3 M3）は最初から文言カタログで作る。旧画面は作り直しで消えるため、旧画面のカタログ化はしない（無駄な二重作業を避ける）。
- ガード: 新画面のディレクトリでは、日本語の直書きを禁止。

---

## 4. 層の規則（G15）

```
web_app/routes（API の入口）→ web_app/services（画面向けの組み立て）→ core（業務・基盤）
workers（ジョブ実行）→ core
core → core/providers（外部サービス）
```

- `core` は `web_app` を読み込まない（今は `app_shutdown.py` と `service_detector.py` が逆向き）。
- `routes` は `core` の重い処理（レンダー・音声合成・画像生成）を直接呼ばず、必ずジョブとして登録する（AGENTS.md の「長時間処理はジョブ化」をガードで保証する）。
- ガード（AST の import 走査）: 上の向きに反する読み込みを禁止。`routes` から読み込んでよい `core` モジュールを許可リストで管理する。

---

## 5. 他にも直したい「設計が微妙なところ」（ガードでは防げないもの）

| # | 問題 | 方針 | どこで |
|---|---|---|---|
| D1 | 台本テキスト（独自記法）が正本で、部分修正ができない | 構造化プロジェクト（Scene / Line）を正本に | v3 §4・M2 |
| D2 | 設定 DB とチャンネル別 metadata.db の二重構造 | `picocast.db` に統合 | v3 §4・M2 |
| D3 | 初期データの経路が2本（`SEED/prompt_packs/product` と `prompt_profiles/genres`） | パック形式に一本化 | v2 T9・T30 |
| D4 | 「Web UI が起動中でないと自動運用が進まない」 | OS タスクの tick と画面の分離 | v2 T19・v3 §3.2 |
| D5 | 設定の即時反映を `sys.modules` 全走査で実現 | 使う時点で読む（G2） | M0〜M2 |
| D6 | 生成の全工程やり直し | 入力ハッシュによる工程キャッシュ | v3 §5・M2 |
| D7 | 画面ごとに同じ部品（ジョブ監視・確認ダイアログ・トースト）を書いている | 共通 UI 部品（新 SPA で最初から） | v3 M3 |
| D8 | テストで時刻・チャンネル・設定をモンキーパッチで差し替えている | `clock.freeze`・`channel_id` 引数・`settings.override()` の正式な差し替え口 | G1〜G3 と同時 |

---

## 6. 進め方

1. **M0 で最初にやる**: ガードの土台（§1.1）→ G1 時刻（違反ゼロまで）→ G15 層の規則 → G4・G5・G6・G8・G11・G12・G13（ベースライン付きで導入し、新しい違反を止める）→ G7（再試行・費用）→ G10（ガード導入）。
2. M2 で G2・G3・G9・G10 をゼロにする（データモデルの作り直しと同時に行うと二度手間にならない）。
3. 各ガードを入れた PR で AGENTS.md に1行の規則を追加し、`review-nvf-changes` スキルの共通観点に「共通基盤を通しているか（ガードの許可リストを増やしていないか）」を加える。
4. ベースラインの件数推移を HANDOFF.md に記録する（減ることだけを確認）。
