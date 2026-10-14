# 製品化 v2 設計（ライセンス強化・ブランド刷新・機能改善）

最終更新: 2026-10-14
実装担当: Codex（この文書を正本として段階ごとにコミットする。進捗と決定待ちは HANDOFF.md）
前提: 署名付きライセンスキー v1 と端末固定ライセンス v2（T1〜T4）は実装済み。本書は設計正本として残す。以後の未着手カードと運用受入は `HANDOFF.md` を参照する。

---

## 0. 決定事項と未決事項

| 項目 | 状態 | 内容 |
|---|---|---|
| 販売形態 | 決定 | Windows 向け買い切り＋ジャンルパック別売り。BOOTH で販売 |
| エディション | 決定 | 体験版（透かし・1ch・1日3本・投稿可・Analytics/自動運用不可）/ Standard（1ch）/ Pro（ch無制限） |
| キー発行 | 決定 | 自前 RSA 署名キー。Google スプレッドシート＋Apps Script で自動発行 |
| キーの端末固定 | **本書で設計** | 端末コードを含む「アクティベーション証明書」方式（§1） |
| 製品名 | 決定（2026-10-14） | **PicoCast**。§2.2 の対応表どおりに改名する |
| リポジトリ名 | 製品名に従う | 製品名決定後に変更（§2.4） |
| 機能改善 | 提案 | §3。採否は利用者が決める。着手順の推奨は §4 |
| 多言語対応 | 要望あり（2026-10-14） | §3.5 と T13。L1（YouTube メタデータ）から段階的に |
| 製品化の必須改修 | 追加（2026-10-14） | §3.6 と T15〜T28。P1〜P8 は販売開始前に必須 |
| 無料アップデート期間 | 仮 | 1年（`tools/license/gas/Code.gs` の `UPDATE_MONTHS`） |

---

## 1. ライセンス v2: 端末固定アクティベーション

### 1.1 目的と脅威モデル

- 防ぎたいこと: キーの共有（知人・掲示板への貼り付け）、1ライセンスでの多数PC利用、DB の書き換えによる上位版化（v1 で対応済み）。
- 防がないこと（割り切り）: exe の改造によるチェック除去。Nuitka の C コンパイルで解析コストを上げるに留める。
- 守ること: オフラインで使い続けられる、PC 買い替え・OS 再インストール時に購入者が自分で復旧できる。

### 1.2 方式: ライセンスキー（購入の証明）＋ アクティベーション証明書（端末の証明）

```
購入 ─▶ ライセンスキー（v1 と同じ。端末に依存しない「購入の証明」）
            │
アプリ ─────┤ 端末コード（このPCの指紋のハッシュ）を表示
            ▼
アクティベーション API（Apps Script doPost）
  - キー署名を検証 → 発行済みシートで失効なし確認
  - そのライセンスの有効端末数 < 上限（Standard 2台 / Pro 3台）なら登録
  - {lid, ed, packs, mid, iat, exp} に署名した「証明書」を返す
            ▼
アプリ: 証明書を保存。起動のたびに「署名OK」かつ「mid == 現在の端末コード」を検証
```

- **端末コード `mid`**: `SHA-256(製品ID + 端末の固有ID)` の先頭 32 hex。生IDは送らない・保存しない。
  - Windows: `HKLM\SOFTWARE\Microsoft\Cryptography\MachineGuid`（OS 再インストールで変わる。部品交換では変わらない）
  - macOS: `IOPlatformUUID`（`ioreg -rd1 -c IOPlatformExpertDevice`）
  - 取得失敗時は例外で停止し（フォールバック禁止）、`E-LICENSE-MACHINE` を表示する。
- **証明書の保存**: `settings.LICENSE_ACTIVATION` に保存。さらに Windows では DPAPI（`core/secret_store.py` と同じ仕組み）で暗号化し、他PCへ DB をコピーしても復号できないようにする（二重の端末固定）。
- **オフライン猶予（リース）**: 証明書に `exp`（発行から 30 日）を持たせる。期限の 7 日前から起動時に自動更新を試み、通信できなければ期限まで通常動作・期限切れで体験版へ戻す（理由を画面表示）。
  - 失効（返金）は次回更新時に反映される。最長 30 日の遅れを許容する。
  - 猶予日数・更新開始日数は `config.py` 定数（`LICENSE_LEASE_DAYS` / `LICENSE_RENEW_BEFORE_DAYS`）。
- **オフライン専用の購入者**向けに、手動アクティベーションも用意する: アプリが「端末コード」を表示 → 購入者がフォーム（またはメール）で送る → 販売者側の Apps Script が `exp` なしの証明書を返信。リース更新は不要だが、失効は反映できない（台数上限の管理は効く）。

### 1.3 端末の入れ替え

- アプリの「このPCの登録を解除」→ API `deactivate`（`lid` + `mid` + 証明書署名で本人確認）→ シートの該当端末を無効化し、枠を1つ戻す。
- PC が壊れて解除できない場合: フォームから「全端末リセット」を申請 → 年 2 回までは自動承認（シートに回数記録）、それ以上は販売者の手動承認。

### 1.4 スプレッドシート（v1 からの追加）

| シート | 列 |
|---|---|
| 端末 | license_id / mid / 登録日時 / 最終更新日時 / 状態（有効・解除済み） / アプリ版 |
| リセット申請 | license_id / 申請日時 / 承認（自動・手動） |

### 1.5 API（Apps Script Web アプリ `doPost`）

| action | 入力 | 出力 |
|---|---|---|
| `activate` | license_key, mid, app_version | 証明書 または `{error: "limit" / "revoked" / "invalid"}` |
| `renew` | 証明書 | 新しい証明書（exp 延長） または error |
| `deactivate` | 証明書 | `{ok: true}` |

- v1 の `doGet ?lid=`（失効確認）は `renew` に統合して廃止する。`LICENSE_REVOCATION_CHECK_URL` は `LICENSE_API_URL` に改名。
- 同時実行は `LockService` で直列化（v1 の `onFormSubmit` と同じ）。

### 1.6 アプリ側の改修

| ファイル | 内容 |
|---|---|
| `core/machine_id.py`（新規） | OS 別に端末コードを計算する。テストではモンキーパッチで固定 |
| `core/license_key.py` | 証明書（`NVA1.` 接頭辞）の検証を追加。キーと同じ RSA 鍵で署名 |
| `core/license_manager.py` | edition 判定を「キー検証」から「証明書検証（署名・mid・exp）」へ。キーだけで証明書が無い状態は `status=not_activated`（体験版扱い） |
| `web_app/routes/api_settings.py` | `POST /license`（キー登録→即アクティベート）、`POST /license/renew`、`POST /license/deactivate`、`GET /license/machine-code` |
| 設定画面 | 端末コード表示、登録台数、期限、解除ボタン、手動アクティベーションの貼り付け欄 |
| `core/error_codes.py` | `E-LICENSE-MACHINE`（端末コード取得失敗）、`E-LICENSE-LIMIT-DEVICES`（台数上限）、`E-LICENSE-EXPIRED`（リース切れ） |
| `tools/license/gas/Code.gs` | `doPost` の4アクションと2シート |

### 1.7 ガードを強める追加策（コストが小さい順）

1. **検証箇所の分散**: `current_limits()` だけでなく、レンダー時の透かし判定（`native_renderer.should_watermark`）とアップロード直前で、それぞれ独立に証明書を検証する（1箇所の改造で全解除されないように）。共通関数は1つにし、呼び出し点を増やす（コピペ禁止）。
2. **購入者名の表示**: 設定画面とヘッダーの「ライセンス」表示に購入者名を出す（共有の心理的抑止）。
3. **体験版透かしに端末コードの一部を入れない**（プライバシー優先。入れない判断を明記）。
4. **公開鍵のピン留め**: 公開鍵の SHA-256 をコード内の別モジュールにも持ち、起動時に一致を検証（公開鍵の差し替え改造への対策）。
5. やらないこと: 難読化ツールの追加、デバッガ検知、常時オンライン必須化（買い切り製品の体験を損なうため）。

### 1.8 テスト

- 端末コードが一致しない証明書・期限切れ証明書・他鍵で署名した証明書が体験版になる。
- 台数上限・解除・リセット回数のロジックは Apps Script 側なので、`tools/license/gas/` に対応表を README で残し、手動確認手順を書く。
- 起動時の自動更新が通信失敗しても期限内は製品版のまま（画面に最終更新日時とエラー）。

---

## 2. ブランド刷新（製品名・ディレクトリ・リポジトリ）

### 2.1 製品名の候補

PicoAgent と並ぶ「Pico シリーズ」にすると、ブランドを共有でき、LP・サポート・購入者層も相互送客できる。

| 候補 | 意味・狙い | 備考 |
|---|---|---|
| **PicoCast**（推奨） | Pico シリーズ＋放送/配信（cast）。短く、英日どちらでも読める | PicoAgent と並べて覚えやすい |
| PicoReel | Pico＋リール（ショート動画） | Shorts 寄りの印象が強い |
| PicoStudio | Pico＋制作スタジオ | 汎用的で埋もれやすい |
| ReelPilot | 自動運用（autopilot）を前面に | Pico シリーズから外れる |
| TubeLoom | 台本・声・絵を「織る」 | 独自性は高いが意味が伝わりにくい |

- キャラクター名（ずんだもん等）・「YouTube」・「VOICEVOX」を製品名に入れない（他者の商標・キャラクター規約）。
- 公開前に、商標検索（J-PlatPat）と BOOTH・GitHub・ドメインでの同名確認を利用者が行う。

### 2.2 命名の対応表（PicoCast の場合）

| 対象 | 現在 | 変更後 |
|---|---|---|
| 製品表示名 | Native Video Factory | PicoCast |
| 短縮識別子 | `NVF` / `nvf` | `PCST` / `picocast`（キー接頭辞は `PC1.`、証明書は `PCA1.`） |
| exe | `NativeVideoFactory.exe` | `PicoCast.exe` |
| データ保存先（exe 版） | exe と同じフォルダ | `%LOCALAPPDATA%\PicoCast\`（開発版は `PicoCast-Dev`。PicoAgent の分離規則に合わせる） |
| タスクスケジューラ | `NativeVideoFactory-FixedComment-*` | `PicoCast-FixedComment-*` |
| 環境変数 | `NVF_MASTER_KEY` / `NVF_DISABLE_JOB_RUNNER` | `PICOCAST_MASTER_KEY` / `PICOCAST_DISABLE_JOB_RUNNER` |
| User-Agent | `NVF-update-check` 等 | `PicoCast/<version>` |
| スキル名 | `*-nvf-*` | `*-picocast-*` |
| ローカルフォルダ | `C:\00_PG\00_yukkurijidou` | `C:\00_PG\22_PicoCast`（PicoAgent=20, LP=21 の並び） |
| GitHub | `benybeny777/yukkurijidou` | `benybeny777/PicoCast` |
| 配布物リポジトリ（任意） | なし | `benybeny777/PicoCast-Distribution`（LP・latest.json・リリース。PicoAgent と同じ構成） |

### 2.3 移行（既存利用者＝オーナー環境を壊さない）

既存データの移行は「一度だけ明示的に移す」処理として実装し、旧名の探索を常用しない（AGENTS.md のフォールバック禁止）。

1. **保存先**: 起動時、新保存先が空で旧保存先（exe 横の `data/`）に `settings.db` があれば、移行画面を出して利用者の確認後に移動する。移動後は旧場所に `MOVED_TO_PicoCast.txt` を残す。
2. **マスターキー**: Windows は DPAPI のファイルなので保存先移動に追従するだけ。macOS/Linux の keyring サービス名を変える場合は、旧名から読み出して新名へ保存し直す移行を1回だけ行う（`# フォールバック許可: 改名時の一度きりの移行` を付ける）。
3. **タスクスケジューラ**: 既存の自己修復処理（`_self_heal_fixed_comment_task`）に「旧接頭辞のタスクを削除して新名で登録し直す」を追加する。
4. **ライセンスキー**: v1 キー（`NVF1.`）は発行済みが自分用のみのため、改名時に新接頭辞で再発行し、`NVF1.` の受理は削除する（互換を残さない）。
5. **output/ と channel profile**: パスは相対保存なので変更不要。

### 2.4 リポジトリ・ディレクトリ変更の手順（利用者の操作が要るもの）

1. GitHub でリポジトリ名を変更（Settings → Rename）。旧 URL は自動リダイレクトされる。
2. ローカルの `git remote set-url origin https://github.com/benybeny777/PicoCast.git`。
3. 起動中のアプリ・ジョブランナー・タスクスケジューラの登録を止めてから、フォルダを `C:\00_PG\22_PicoCast` へ移動。`.venv` は絶対パスを含むので作り直す（`python -m venv .venv` → `pip install -r config/requirements.txt`）。
4. `yukkurijidou.code-workspace` を `PicoCast.code-workspace` に改名。
5. Codex / Claude のメモリ・プロジェクト設定はフォルダパスに紐づくため、移動後に引き継ぎメモを読み込ませる。

### 2.5 実装順（改名は機械的置換が大半）

1. 製品表示名を `config.py` の定数 `PRODUCT_NAME` / `PRODUCT_SLUG` に集約し、テンプレート・法務文書・メタデータはそこから読む（以後の改名を1か所で済ませる）。
2. `git grep -n "Native Video Factory\|NativeVideoFactory\|NVF\|nvf"` の全件を対応表どおりに置換。テストの期待値も更新。
3. 保存先の `%LOCALAPPDATA%` 化（§2.3-1）。開発版と製品版の分離は `core/runtime_env.py` の `is_frozen()` で判定し、ほかの場所を探さない。
4. ドキュメント・スキル・AGENTS.md の名称更新。

---

## 3. 機能改善案（ガラッと変えてよい前提）

優先度: ★★★ = 売上・継続率に直結 / ★★ = 差別化 / ★ = 将来。

### 3.1 体験の作り直し

| # | 案 | 内容 | 優先 |
|---|---|---|---|
| A | **デスクトップアプリ化** | ブラウザで localhost を開く形から、専用ウィンドウのアプリへ。Python 本体はそのまま、外側を pywebview（軽い）か Tauri（PicoAgent と同じ技術。トレイ常駐・自動更新・インストーラが揃う）で包む。「Web UI を開いてください」が無くなり、製品らしさが大きく上がる | ★★★ |
| B | **3ステップのホーム画面** | 「ネタを選ぶ → 台本を確認 → 投稿予約」だけを並べた初心者向けホーム。今の詳細画面は「詳細モード」に移す | ★★★ |
| C | **シーン編集タイムライン** | 生成後にシーン単位で 台詞・読み・画像・表情 を差し替え、そのシーンだけ再生成・再レンダー。全体やり直しを無くす | ★★★ |
| D | **YouTube 接続ウィザード** | GCP プロジェクト作成から OAuth 同意画面の「本番」化（テストのままだと 7 日でトークン失効）まで画像付きで案内し、JSON の形式とトークン失効を検知 | ★★★ |
| E | **通知** | 自動運用の保留・失敗・投稿完了を Windows 通知＋任意で Discord/メール（Webhook）へ。外部公開はしない | ★★ |

### 3.2 「伸びる動画」を作る機能

| # | 案 | 内容 | 優先 |
|---|---|---|---|
| F | **勝ちパターン学習** | Analytics の上位動画から「冒頭の型・尺・タイトルの型・サムネ構図」を抽出してジャンルごとに保存し、次の台本・タイトル生成のプロンプトに自動で入れる（既存の横展開候補・スコアを発展） | ★★★ |
| G | **量産判定チェッカー** | YouTube の「繰り返しの多いコンテンツ」規約対策。直近の自チャンネル動画との類似度（台本・構成・サムネ）を出し、似すぎなら保留。販売時の安心材料にもなる | ★★★ |
| H | **タイトル・サムネ候補の比較** | 3案ずつ出して選ぶ／投稿後に差し替え候補を提示（YouTube の A/B テスト機能は API 非対応のため手動差し替え支援） | ★★ |
| I | **ネタ在庫（企画ボード）** | ネタを溜めて並べ替え、自動運用が上から消化する。季節・トレンドの締切付きネタ | ★★ |

### 3.3 生成エンジン

| # | 案 | 内容 | 優先 |
|---|---|---|---|
| J | **音声エンジンの追加** | VOICEVOX に加え AivisSpeech・COEIROINK に対応（PicoAgent の Aivis 実装の知見を流用）。ジャンルパックに声を含められる | ★★ |
| K | **ローカル優先モード** | 台本は Ollama、画像は Stable Diffusion WebUI で完結させ、Gemini 費用ゼロで回せるプリセット。費用ダッシュボードで1本あたりの API 費用を表示 | ★★ |
| L | **縦横・他SNS書き出し** | 同じ素材から TikTok / Instagram リール向けの書き出し（投稿は手動。各社 API は審査が重いため後回し） | ★ |

### 3.4 販売・エコシステム

| # | 案 | 内容 | 優先 |
|---|---|---|---|
| M | **ジャンルパック形式 `.pcpack`** | プロンプト・キャラ設定・BGM・サムネ型・読み辞書・NGワードを1ファイルに。署名検証し、ライセンスの `packs` で解放。インストール済み管理と上書き更新（以前の設計案 B1〜B7） | ★★★ |
| N | **PicoAgent 連携** | PicoAgent から「今日の動画を作って」「保留を見せて」と操作できるコネクタ（ローカル API を叩く）。シリーズ製品の相互送客 | ★★ |
| O | **アプリ内アップデート** | `latest.json`（配布リポジトリ）を見て更新を知らせ、ダウンロード・インストーラ起動まで。無料アップデート期限はライセンスの `upd` で判定 | ★★★ |

---

### 3.5 多言語対応（利用者要望 2026-10-14）

多言語対応は、狙いの違う4層に分けて段階的に入れる。上の層ほど費用が小さく効果が早い。

| 層 | 内容 | 効果 | 優先 |
|---|---|---|---|
| L1 **YouTube メタデータの多言語化** | タイトル・説明文を英語などへ翻訳し、YouTube Data API の `localizations`（言語別タイトル・説明）と `defaultLanguage` / `defaultAudioLanguage` を設定する。視聴者の言語設定に合わせて翻訳タイトルが表示される | 日本語の動画のまま海外の検索・おすすめに出る。台本・音声の作り直し不要 | ★★★ |
| L2 **字幕ファイル** | 既存の字幕タイミング（`native_renderer._captions_for_audio_files`）から SRT を書き出し、翻訳 SRT も作る。`captions.insert` でアップロード（1件 400 クォータのため設定で ON/OFF） | 自動翻訳字幕より正確な多言語字幕。焼き込み字幕と別に持てる | ★★ |
| L3 **アプリ画面の多言語化** | 画面・エラー文言・メール文面・法務文書を日本語／英語で切り替える | 海外の購入者に売れる | ★★ |
| L4 **他言語チャンネルの制作** | チャンネルごとに「制作言語」を持ち、台本生成・読み上げ・字幕フォント・NGワードをその言語で行う | 英語圏などのチャンネルを新規に運用できる | ★ |

設計上の前提:

- **原文は日本語のまま**。コードコメント・AGENTS.md・SPEC.md は日本語（AGENTS.md の規則）。多言語化するのは利用者に見える文言と生成物だけ。
- **翻訳エンジン**: 既定は Gemini（既存の `ai_generator`。費用は少額）、ローカル優先モードでは Ollama。翻訳結果はキャッシュして同じ文を2回翻訳しない。機械翻訳であることを画面に明示する。
- **言語コード**は BCP 47（`ja`, `en`, `zh-Hans`, `ko`, `es` など）で統一する。
- **読み上げ**: VOICEVOX は日本語専用。L4 では言語別の音声エンジンが必要になる。候補はローカルで動き商用利用できる Kokoro（Apache-2.0。英・中・日などに対応）や Piper（MIT）。採用前にライセンス・音質・速度を比較して利用者が決める（`audio_backends.py` の既存の切り替え口に追加する）。
- **日本語専用の処理**（よみがな正規化 `reading_normalizer`、SudachiPy）は制作言語が `ja` のときだけ通す。他言語では呼ばない（別処理へのフォールバックにしない）。
- **販売面**: BOOTH は海外購入にも対応しているが、海外向けの本格販売は L3 完了後に判断する。英語版の法務文書は翻訳だけでなく販売者の確認が必要。

### 3.6 製品化に必要な機能改修（自分用ツール → 他人の PC で動く製品）

§3.1〜3.5 は「売れる・差別化する」ための改善。ここは**他人の PC で、サポートなしで動くための必須改修**。販売開始前に P1〜P8 を終える。

| # | 改修 | 現状の問題（コードで確認済み） | 優先 |
|---|---|---|---|
| P1 | **ハードウェアに合わせた初期設定** | 動画エンコーダの既定が `h264_nvenc`（`native_renderer.py:1214`）。NVIDIA 以外の PC では初回の動画生成で失敗する | 必須 |
| P2 | **外部ソフトのワンクリック導入** | VOICEVOX・ffmpeg は「自分でダウンロードしてパスを設定」（`service_detector.py` の案内のみ）。購入者が最初につまずく場所 | 必須 |
| P3 | **APIキーなしで1本作れる初回体験** | 初回の生成に Google API キーが要る。体験版で「すぐ完成動画を見る」ことができない | 必須 |
| P4 | **AI 生成コンテンツの申告** | `containsSyntheticMedia` が常に `False`（`youtube_uploader.py:576`）。YouTube の規約上、実写と見分けがつかない合成コンテンツは申告が必要。販売物で固定値は危険 | 必須 |
| P5 | **アプリを閉じても自動運用が動く** | 自動運用は Web UI プロセスが動いている間だけ進む。固定コメントと同じく OS のタスクで起動する仕組みが無い | 必須 |
| P6 | **長時間処理中のスリープ防止** | レンダー・自動運用の途中で PC がスリープするとジョブが止まる。スリープ抑止の処理が無い | 必須 |
| P7 | **データの自動保護** | バックアップは手動のみ（`backup_service.create_backup`）。DB 移行前の自動退避・定期バックアップ・起動時の整合性検査が無い | 必須 |
| P8 | **ディスク容量の自動管理** | 生成動画・中間ファイルが溜まり続ける。投稿済み動画の素材を整理する方針が無い（容量チェック `disk_check` は止めるだけ） | 必須 |
| P9 | **健康診断ダッシュボード** | VOICEVOX 停止・トークン失効・API キー不正・ディスク残量・YouTube クォータを1画面で見て「直す」ボタンで対処できる画面が無い（情報は各所に散在） | 推奨 |
| P10 | **サポート送信** | 診断 ZIP は作れるが、送る手段が利用者任せ。同意のうえでサポートへ直接送る導線が無い | 推奨 |
| P11 | **費用の見える化と月間上限** | 自動運用には日次の有料 API 上限があるが、手動生成を含めた月間の費用表示・上限が無い | 推奨 |
| P12 | **YouTube クォータの管理** | 1日 10,000 ユニットの残りを把握せず、投稿の途中で枠切れになり得る | 推奨 |
| P13 | **アプリ内ヘルプ** | エラーコードに対処文はあるが、画面からマニュアル・FAQ へ飛べない | 推奨 |
| P14 | **アンインストールとデータ削除** | 利用者データ（DB・認証情報・動画）を一括で書き出す／消す手段が無い（プライバシーポリシー上も必要） | 推奨 |

- P1〜P8 は「無いと返金・問い合わせになる」もの、P9〜P14 は「サポート負荷を減らす」もの。
- 詳細仕様は §4 の T15〜T28。


---

## 4. タスクカード（Codex 向け）

推奨の着手順（販売開始に必要なものを先に。依存が満たされたものから）:

1. ライセンス: T1 → T2 → T3 → T4（2026-10-14 に実装済み）
2. 依存なしの必須改修: T15（エンコーダ）、T18（AI 申告）、T20（スリープ防止）、T22（ディスク整理）
3. 改名と保存先: T5 → T6
4. 保存先に依存する必須改修: T16（外部ソフト導入）、T19（自動運用の OS タスク）、T21（自動バックアップ）
5. 初回体験とサポート: T17（サンプル動画）、T8（YouTube 接続ウィザード）、T23（健康診断）、T24（サポート送信）
6. 販売・差別化: T9（パック）、T11（アプリ内更新）、T10（量産判定）、T13 L1・L2（多言語メタデータ・字幕）
7. 大きな作り直し: T12（デスクトップアプリ化、要承認）、T13 L3・L4、T25〜T28、番号なしの改善案


共通ルール:
- 1カード＝1コミット（大きいものは「段」ごとに分ける）。各コミットで `./.venv/Scripts/python.exe -m pytest -q` を通し、README / SPEC / CHANGELOG を同時更新する（AGENTS.md）。
- 進捗は `HANDOFF.md` の「タスク状態」表を更新してコミットに含める（クレジット切れ・担当交代に備える）。
- 「要決定」のカードは、利用者の決定が HANDOFF.md に記録されるまで着手しない。
- エラーは `core/error_codes.py` の `E-...` コードで返す。フォールバックは本書に「許可」と書いたものだけ。

### T1. 端末コード（`core/machine_id.py`）  依存: なし

- `machine_code() -> str`: `sha256(PRODUCT_ID + ":" + raw_id)` の hex 先頭 32 文字。`PRODUCT_ID` は `config.py` 定数（§2 の改名で新名に変える。現時点は `nvf`）。
- `_raw_machine_id()`:
  - Windows: `winreg` で `HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Cryptography` の `MachineGuid`（`KEY_READ | KEY_WOW64_64KEY`）。
  - macOS: `ioreg -rd1 -c IOPlatformExpertDevice` 出力の `IOPlatformUUID`（`subprocess.run(..., timeout=5, check=True)`）。
  - それ以外・取得失敗: `AppError("E-LICENSE-MACHINE", ...)`。空文字や固定値で続けない。
- 生 ID はログ・画面・送信に出さない。ハッシュのみ。
- テスト: `_raw_machine_id` をモンキーパッチし、同じ入力で同じコード・別入力で別コード・失敗時に AppError。
- 受入: `GET /api/settings/license/machine-code` が `{"machine_code": "<32hex>"}` を返す。

### T2. アクティベーション証明書の検証（アプリ側）  依存: T1

- 形式: `NVA1.<payload>.<signature>`（キーと同じ RSA 鍵・同じ署名方式。`core/license_key.py` の base64 処理と署名検証を共通化して使う。写さない）。
- payload: `{"v":1, "lid", "ed", "packs", "buyer", "upd", "mid", "iat", "exp"}`。`exp` は ISO 日時（UTC）。手動アクティベーションでは空文字＝無期限。
- `core/license_manager.py`:
  - 状態: `unregistered` / `not_activated`（キーのみ）/ `active` / `expired` / `machine_mismatch` / `invalid` / `revoked`。`active` 以外は edition=`trial`。
  - 判定は「証明書の署名OK」かつ「`mid == machine_code()`」かつ「`exp` 未経過」かつ「キーの `lid` と証明書の `lid` が一致」。
  - 保存: `settings.LICENSE_ACTIVATION`。Windows では `core/secret_store.py` の DPAPI 保護関数で暗号化して保存する（新しい暗号化処理を書かず、既存関数を公開して使う）。
  - `get_license_info()` に `machine_code`、`activation_expires_at`、`activation_status` を追加。
- 検証箇所の分散（§1.7-1）: `current_limits()` に加え、`native_renderer` の透かし判定と、`upload_service` / `autopilot_service._upload` の直前で `license_manager.verify_activation_now()`（キャッシュを使わず毎回検証する1関数）を呼ぶ。
- 公開鍵のピン留め（§1.7-4）: `core/license_public_key.py` の PEM の SHA-256 を `core/license_key.py` に定数で持ち、検証前に一致を確認。不一致は `E-LICENSE-INVALID`。
- テスト（`tests/test_license_key.py` に追加）: 端末不一致・期限切れ・lid 不一致・他鍵署名・ピン不一致がすべて trial。正常時は edition が反映される。

### T3. アクティベーション API（Apps Script）  依存: なし（T2 と並行可）

- `tools/license/gas/Code.gs` に `doPost(e)` を追加。本文 JSON `{"action": "...", ...}`、応答 JSON。
  - `activate {license_key, machine_code, app_version}`:
    1. キーの署名を Apps Script 側でも検証する（`Utilities.computeRsaSha256Signature` は署名専用のため、「同じ payload を再署名して一致比較」で検証する）。
    2. 「発行済み」で lid を探し、失効なら `{error: "revoked"}`。
    3. 「端末」シートで lid の有効端末を数える。同じ mid が有効ならそのまま再発行。上限（`CONFIG.DEVICE_LIMITS = {standard: 2, pro: 3}`）以上なら `{error: "limit", devices: [{mid の末尾6桁, 最終更新}]}`。
    4. 端末を登録（または最終更新を更新）し、`exp = 現在 + LEASE_DAYS(30)` の証明書を返す。
  - `renew {activation}`: 証明書を再署名比較で検証 → 失効・端末無効なら error → exp を延ばした証明書。
  - `deactivate {activation}`: 該当端末を「解除済み」にする。
  - `reset {license_key, order_number}`: 「リセット申請」に記録し、その年の2回目までは全端末を自動解除。3回目以降は `{error: "manual_review"}` を返して販売者へメール。
- v1 の `doGet ?lid=` は削除し、README の設置手順を更新。シート「端末」「リセット申請」を README に追加。
- 受入: README の手動確認手順（GAS エディタから `testActivate()` などを実行）で各分岐を確認できる。

### T4. アプリの API と画面  依存: T2, T3

- `config.py`: `LICENSE_REVOCATION_CHECK_URL` を `LICENSE_API_URL` に改名し、`LICENSE_LEASE_RENEW_BEFORE_DAYS`（既定 7）を追加。`LICENSE_REVOCATION_CHECK_INTERVAL_DAYS` は削除。
- `POST /api/settings/license {license_key}`: キー検証 → `activate` 呼び出し → 証明書保存。API 未設定・通信失敗時は `not_activated` で保存し、画面に手動アクティベーションを案内する（自動で別経路に切り替えない）。
- `POST /api/settings/license/activation {activation}`: 手動アクティベーション（メールで届いた証明書の貼り付け）。
- `POST /api/settings/license/renew`、`POST /api/settings/license/deactivate {confirmed: true}`（破壊的操作のため確認必須）。
- 起動時（`web_app/app.py` lifespan の既存スレッド）: `exp` まで `LICENSE_LEASE_RENEW_BEFORE_DAYS` 日以内なら `renew`。失敗は `_logger.warning` と画面表示。コメント `# フォールバック許可: 期限内はオフラインでも製品版のまま動かす（利用者決定 2026-10-14）` を付ける。
- 画面（設定 > 製品管理 > ライセンス）: 端末コード（コピーボタン）、状態、期限、台数上限エラー時の端末一覧、「このPCの登録を解除」、手動アクティベーション欄。
- `core/error_codes.py`: `E-LICENSE-MACHINE` / `E-LICENSE-LIMIT-DEVICES` / `E-LICENSE-EXPIRED` / `E-LICENSE-API`。
- 受入: API をモックしたテストで、activate → active、limit → エラー表示、renew 失敗でも期限内は active、期限切れで trial。

### T5. 製品名の定数化と一括改名  依存: なし（製品名は PicoCast に決定）

- `config.py` に `PRODUCT_NAME`（表示名）、`PRODUCT_SLUG`（exe・フォルダ・タスク名）、`PRODUCT_ID`（端末コードの塩）、`LICENSE_KEY_PREFIX` / `LICENSE_ACTIVATION_PREFIX` を定義する。`git grep -n "Native Video Factory\|NativeVideoFactory\|NVF\|nvf"` の全件を、これらの参照か新名へ置換する（§2.2 の表）。
- 文書・法務文書（`legal/`）・スキル名（`.agents/skills/*-nvf-*` と `.claude/skills/` の入口）・`build_exe.ps1`・`make_codesign_cert.ps1`・テストの期待値も対象。
- 環境変数 `NVF_MASTER_KEY` の改名は keyring の移行と同時に行う（§2.3-2）。
- 受入: `git grep -n "Native Video Factory\|NativeVideoFactory\|NVF_\|\bnvf\b"` が CHANGELOG の過去記録以外 0 件。

### T6. 保存先の分離と移行  依存: T5

- `core/runtime_env.py:app_base_dir()`: exe 版は `%LOCALAPPDATA%\<PRODUCT_SLUG>`（macOS は `~/Library/Application Support/<PRODUCT_SLUG>`）、開発版はリポジトリ直下のまま。他の場所を探さない。
- 初回起動時、新保存先に `data/settings.db` が無く、exe と同じフォルダに `data/settings.db` があれば、`/migrate` 画面で移動を確認 → `data/` と `output/` を移動 → 旧場所に `MOVED_TO_<PRODUCT_SLUG>.txt` を置く。移動はコピー → 検証 → 旧側削除の順にし、失敗時は中止して理由を表示する（部分移動を残さない）。
- `core/fixed_comment_task.py`: 自己修復で旧接頭辞 `NativeVideoFactory-FixedComment-*` のタスクを削除し、新名で再登録する。
- 受入: 一時ディレクトリで旧配置を作るテストで、移動・再実行時に何もしないこと・失敗時のロールバックを確認する。

### T7. リポジトリ・フォルダの変更  依存: T5, T6（利用者の操作）

- §2.4 の手順を利用者に案内し、完了後に README のクローン URL と `*.code-workspace` 名を更新する。Codex が GitHub のリポジトリ名を勝手に変えない。

### T8. YouTube 接続ウィザード（改善案 D）  依存: なし

- 新画面 `/setup/youtube`（既存の `/setup` から遷移）。手順: ①GCP プロジェクト作成 ②YouTube Data API v3 / YouTube Analytics API の有効化 ③OAuth 同意画面（外部・**本番**へ公開）④OAuth クライアント（デスクトップアプリ）を作成し JSON を貼り付け ⑤認可テスト。各手順に公式画面への直リンクと注意点を付ける。
- JSON 検証: `installed` キーがあり、`client_id` / `client_secret` / `redirect_uris` が揃うこと。`web` タイプは理由付きで拒否する。保存は既存の `POST /api/settings/client-secrets`。
- トークン失効の検知: refresh 時の `invalid_grant` を `E-YOUTUBE-TOKEN-EXPIRED`（新設）にし、「同意画面がテストのままだと7日で失効する」という対処を表示する。
- 受入: 不正 JSON 3種の拒否テストと、`invalid_grant` のエラー変換テスト。

### T9. ジャンルパック（拡張子は改名後の製品名に合わせる）（改善案 M）  依存: T2（packs 判定）

- zip 構成: `manifest.json`（`pack_id`, `version`, `title`, `min_app_version`, `free`, `files` の SHA-256 一覧）、`manifest.sig`（manifest への RSA 署名。キーと同じ鍵）、`genre/`（`config/prompt_profiles/genres/<genre>/` と同じ構成）、`characters/`、`bgm/`、`reading_dict.json`、`ng_words.json`。
- `core/pack_store.py`（新規）: 署名・ハッシュを検証 → `<保存先>/packs/<pack_id>/<version>/` に展開 → DB の `installed_packs(pack_id, version, installed_at)` に記録。テンプレート・キャラ・BGM に `source_pack_id` / `source_pack_version` / `user_modified` を持たせる。再インストール時は `user_modified=0` だけ上書きし、`1` は画面で利用者に選ばせる。
- 解放判定: ライセンスの `packs` に `pack_id` があるか、manifest の `free` が true。
- 製品同梱の `config/SEED/prompt_packs/product` も同じ形式の無料パックとして扱い、seed の経路を一本化する（`channel_profile.py:238` と `prompt_profile_loader.py:22` の二重経路を解消）。
- 作成ツール: `tools/pack/build_pack.py <genre_dir> --pack-id ... --version ...`（秘密鍵で署名）。
- 受入: 改ざん zip の拒否、未購入パックのロック、上書き更新で `user_modified` が保たれることのテスト。

### T10. 量産判定チェッカー（改善案 G）  依存: なし

- 生成済みの台本（`metadata.db.videos.script_content`）を、同じチャンネルの直近 N 本（`config.py` 定数）と比べて類似度を計算する。指標は文字 3-gram の Jaccard と、構成（シーン数・見出しの型）の一致率。外部 API は使わない。
- 閾値（`config.py`）を超えたら、自動運用は `held`（`E-AUTO-SIMILAR` を新設）、手動生成は警告表示のみ。
- 受入: 同一台本・軽微な改変・別台本の3ケースのテスト。

### T11. アプリ内アップデート（改善案 O）  依存: T5

- `update_check.py` の JSON を `{"latest_version", "url", "sha256", "notes", "released_at"}` に拡張する。ライセンスの `upd`（無料アップデート期限）より `released_at` が後なら「有償アップグレード」と表示する。
- ダウンロードは `<保存先>/updates/` へ保存し、SHA-256 の一致を確認してからインストーラを起動してアプリを終了する。不一致ならファイルを削除して中止する。
- 受入: 期限内・期限後・ハッシュ不一致のテスト。

### T12. デスクトップアプリ化（改善案 A）  依存: T5, T6

- 段1（推奨）: `pywebview` でウィンドウを開き、内部で既存の uvicorn を起動する入口 `web_app/desktop.py` を追加する。`--open-browser` は開発用に残す。トレイ常駐は段2。
- 技術選定の比較（pywebview / Tauri＋Python サイドカー）を PR 本文に書き、利用者の承認後に着手する（配布サイズ・自動更新・署名の差が大きいため）。

### T13. 多言語対応（§3.5）  依存: L1・L2 はなし、L3 は T5 の後、L4 は L3 の後

段ごとに1コミット以上。各段の着手時に、この節の仕様を現行コードと照合してから進める。

**L1 YouTube メタデータの多言語化**
- `config.py`: `YOUTUBE_LOCALIZATION_LANGUAGES`（既定は空＝無効。例 `["en", "zh-Hans", "ko"]`）、`YOUTUBE_DEFAULT_LANGUAGE`（既定 `ja`）。チャンネルごとに変えられるよう channel profile にも同名の上書き項目を持たせる。
- `core/translation.py`（新規）: `translate(texts: list[str], target: str, *, kind: str) -> list[str]`。Gemini / Ollama を設定で切り替え、`metadata.db` の `translation_cache(source_hash, target, kind, text)` に保存。失敗は `E-TRANSLATE`（新設）で止め、未翻訳のまま投稿しない。
- `core/youtube_uploader.py`: 投稿時（と後からの一括適用）に `snippet.defaultLanguage` / `snippet.defaultAudioLanguage` と `localizations = {lang: {title, description}}` を設定。タイトルは YouTube の100文字制限を翻訳後に検査し、超過は再翻訳（短く）→ それでも超過ならエラー。
- 画面: 投稿確認画面に言語別タイトル・説明の確認と手修正欄。既存動画へ一括適用するジョブ（`job_manager` 経由）。
- 受入: 翻訳をモックしたテストで `localizations` の組み立て、100文字超過の扱い、キャッシュの再利用。

**L2 字幕ファイル**
- `core/subtitles.py`（新規）: レンダー時に使った字幕チャンクとタイミングから `captions_<lang>.srt` を動画フォルダに書き出す（焼き込みと同じタイミング源を使い、別計算を書かない）。
- 翻訳 SRT は L1 の `translate()` を使う。
- `captions.insert` でのアップロードは `YOUTUBE_UPLOAD_CAPTIONS`（既定 OFF。クォータ 400/件の注意を画面に表示）。
- 受入: SRT の時刻書式・連番・改行のテスト、翻訳 SRT の行数が原文と一致すること。

**L3 アプリ画面の多言語化**
- 文言カタログ `web_app/i18n/ja.json`（原文）と `en.json`。キーは `画面名.要素名`。Jinja には `t("key")`、JS には `window.t("key")`（`base.html` で現在言語のカタログを埋め込む）。
- 設定 `UI_LANGUAGE`（既定 `ja`。初回セットアップで選択）。
- `core/error_codes.py` の `ErrorDef.message` / `remediation` をカタログキー参照に変え、`format_error()` が現在言語で返す。英語訳が無いキーは**起動時の検査テストで失敗させる**（実行時に日本語へ黙って戻さない）。
- 対象の洗い出し: `web_app/templates/*.html`（19ファイル）、`web_app/static/*.js`、`core/error_codes.py`、Apps Script のメール文面、`legal/`（英語版は `legal/en/`）。
- 移行は画面単位で段階的に進め、カタログ化済みの画面を HANDOFF.md に記録する。
- 受入: `ja.json` と `en.json` のキー集合が一致するテスト、テンプレートに直書きの日本語が残っていないかの検査（カタログ化済み画面のみ対象）。

**L4 他言語チャンネルの制作**
- channel profile に `content_language`（既定 `ja`）。ジャンルパック（T9）の manifest に `language` を持たせ、言語が合うパックだけ選べる。
- 台本プロンプト・NGワード・タイトル規則は言語別テンプレートとして DB に持つ（`prompt_templates` に `language` 列）。
- 音声エンジンの選定（Kokoro / Piper など）は利用者の承認後。`audio_backends.py` に追加し、`content_language` とエンジンの対応を検証して不一致はエラー。
- `reading_normalizer` は `content_language == "ja"` のときだけ呼ぶ。
- 字幕フォントを言語別に設定（`config.py`）。
- 受入: `en` チャンネルで台本 → 音声 → 動画が日本語処理を通らずに完走する統合テスト（音声エンジンはモック）。

### T15. ハードウェアに合わせた初期設定（P1）  依存: なし

- 初回セットアップ（と設定画面の「再検出」）で、既存の `gui_support` / `external_service_check` のエンコーダ検出結果を使い、`NATIVE_FFMPEG_ENCODER` を `h264_nvenc` → `h264_qsv` → `h264_amf` → `libx264` の順で**実際に短いテストエンコードが通ったもの**に設定して DB に保存する。
- 実行時にエンコーダを自動で切り替えない（AGENTS.md のフォールバック禁止）。保存済みのエンコーダが失敗したら `E-RENDER-ENCODER`（新設）で止め、「設定画面で再検出」を案内する。
- コード中の既定値 `h264_nvenc` は `config.py` の既定値（`libx264`＝どの PC でも動く）に寄せ、ハードコードを消す。
- GPU・メモリから「画質プリセット（軽量／標準／高画質）」の既定も同時に決める（画像生成解像度・並列数）。
- 受入: エンコーダ検出をモックし、NVIDIA なし環境で `libx264` が保存されるテスト。

### T16. 外部ソフトのワンクリック導入（P2）  依存: T6（保存先）

- ffmpeg: 公式配布（gyan.dev の essentials ビルド等）の固定版 URL と SHA-256 を `config.py` に持ち、`<保存先>/tools/ffmpeg/` へダウンロード → ハッシュ検証 → 展開 → `FFMPEG_BIN` を保存。ハッシュ不一致は削除して中止。版の更新は `audit-nvf-dependencies` スキルで行う。
- VOICEVOX: 再配布条件を確認するまでは同梱・自動ダウンロードしない。公式ページを開き、インストール後に「再検出」で自動設定（既存 `service_detector`）。インストール済みなら VOICEVOX をアプリから起動・終了できるようにする（`VOICEVOX_PATH`）。
- Ollama・Stable Diffusion WebUI は任意のまま、案内のみ。
- 受入: ダウンロード・ハッシュ検証・展開をモックしたテスト（不一致で何も残らない）。

### T17. APIキーなしの初回体験（P3）  依存: T9（パック）があれば同梱サンプルをパックにする

- `/setup` の最後に「サンプル動画を作る」: 同梱のサンプル台本＋同梱の背景画像（`assets/` または標準パック内）で、Gemini・画像生成 API を使わずに VOICEVOX＋ffmpeg だけで1本作る。既存の `setup_test=true` 経路を使う。
- 完成後に動画を画面で再生し、「次は API キーを登録して自分の台本を AI で作る」へ誘導。
- 受入: Google API キー未登録・画像生成 API 未設定の状態でサンプル生成ジョブが成功するテスト（VOICEVOX はモック）。

### T18. AI 生成コンテンツの申告（P4）  依存: なし

- `containsSyntheticMedia` を固定値からやめ、チャンネル設定 `YOUTUBE_SYNTHETIC_MEDIA_DEFAULT`（`ask` / `true` / `false`、既定 `ask`）と動画ごとの上書きにする。
- `ask` のとき、投稿確認画面で「実在の人物・場所・出来事と見分けがつかない合成映像を含むか」を選ばせ、未選択では投稿できない（自動運用ではチャンネル設定の値を必須にし、`ask` のままなら保留）。
- 説明文への「AI 音声（VOICEVOX:キャラ名）を使用」等のクレジット自動挿入が全チャンネルで有効かも確認する。
- 受入: `ask` のまま投稿 API を呼ぶと 422、自動運用で保留になるテスト。

### T19. アプリを閉じても自動運用が動く（P5）  依存: T6

- `core/fixed_comment_task.py` と同じ方式で、OS のタスク（Windows タスクスケジューラ / macOS launchd）に `<exe> --autopilot-tick` を登録する。間隔は `config.py`（既定 15 分）。
- `--autopilot-tick` は Web UI を起動せず、`workers.runner` と同じ処理で「実行可能な工程を1つ進めて終了」する。Web UI が起動中なら何もしない（二重実行防止はジョブの原子登録で既に保証されているかを確認し、足りなければ DB のロックで保証）。
- 自動運用を ON にしたときだけ登録し、OFF で削除。exe 移動時の自己修復も固定コメントと共通化する（写さない）。
- T12（デスクトップアプリ化）でトレイ常駐にする場合も、この OS タスク方式は残す（PC 起動直後・アプリ未起動でも進めるため）。
- 受入: 登録・削除・自己修復のテスト（固定コメントのテストと同じ形）、Web UI 起動中は tick が何もしないテスト。

### T20. スリープ防止（P6）  依存: なし

- ジョブ実行中だけ OS のスリープを抑止する共通コンテキスト `core/power.py: keep_awake()`。Windows は `SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)`、macOS は `caffeinate -i -w <pid>`。ジョブ終了（成功・失敗・キャンセル）で必ず解除（`with` で解放）。
- `workers.runner` のジョブ実行の合流点で1回だけ使う（各ジョブに散らさない）。
- 受入: OS API をモックし、例外時も解除されるテスト。

### T21. データの自動保護（P7）  依存: T6

- DB スキーマ移行の直前に `settings.db` / 各 `metadata.db` を `<保存先>/backups/auto/<日時>/` へ自動コピー（世代数は `config.py`、既定 5）。
- 起動時に SQLite の `PRAGMA quick_check`。異常なら起動を止めて「バックアップから復元」画面を出す（壊れた DB を空で作り直さない。AGENTS.md の空データ書き戻し禁止）。
- 定期バックアップ（既定 週1、認証情報は既存の暗号化バックアップ形式）を任意で ON。
- 受入: 移行前バックアップが作られる・世代が回るテスト、破損 DB で起動が止まるテスト。

### T22. ディスク容量の自動管理（P8）  依存: なし

- 投稿済み（YouTube に存在を確認済み）の動画について、中間ファイル（音声 WAV・分割画像・作業用動画）を投稿から N 日後に削除する設定（既定 OFF、N は `config.py`）。完成 MP4・サムネ・台本（DB）は残す。
- 設定画面に「出力フォルダの使用量（チャンネル別）」と「今すぐ整理」（`confirmed=true` 必須、削除対象の一覧と合計容量を先に表示）。
- 未投稿・投稿失敗の動画には触れない。YouTube 側の存在確認ができない場合は削除しない（YouTube が正。AGENTS.md）。
- 受入: 投稿済み・未投稿・確認不能の3ケースで、削除されるのが投稿済みの中間ファイルだけであるテスト。

### T23. 健康診断ダッシュボード（P9）  依存: T8, T15

- ホーム（またはヘッダー）に状態一覧: VOICEVOX 接続、ffmpeg、エンコーダ、Google API キーの有効性（軽い呼び出しで検証、費用のかからない API を使う）、YouTube トークン（期限・失効）、ディスク残量、今日の YouTube クォータ見込み、ライセンス状態。
- 各項目に「直す」ボタン（再検出・再認可・設定画面の該当箇所へ移動）。
- 既存の `status_service` を拡張し、新しい状態取得処理を重複して書かない。

### T24. サポート送信（P10）  依存: なし

- 診断 ZIP（既存、秘密値マスク済み）を、利用者の同意チェック後に Apps Script の Web アプリ（ライセンス API と同じデプロイに `action: "support"` を追加）へ送り、受付番号を表示。販売者には受付番号付きのメールが届く。
- サイズ上限（`config.py`）を超える場合は送らずに理由表示。送信内容の一覧を送信前に見せる。

### T25. 費用の見える化と月間上限（P11）  依存: なし

- 既存の `autopilot_budget` の消費記録を手動生成にも広げ、Gemini / 画像生成 / ChatGPT レビューの呼び出しごとに概算費用を記録（単価は `config.py`。為替は固定値を設定画面で変更可）。
- 月間上限（既定なし）を超えたら有料 API を呼ぶ前に `E-BUDGET-MONTHLY`（新設）で止める。
- 画面: 今月の費用・1本あたりの平均・内訳。

### T26. YouTube クォータの管理（P12）  依存: なし

- API 呼び出しごとの消費ユニット（upload 1,600 / captions.insert 400 / videos.update 50 など、値は `config.py`）を日次（太平洋時間の 0 時リセット）で記録。
- 投稿前に「残り見込み < 必要量」なら投稿を翌日に回す（自動運用）／警告（手動）。
- 受入: 消費の集計と日付境界のテスト。

### T27. アプリ内ヘルプ（P13）  依存: T13 L3（多言語）と同時が効率的

- `MANUAL.md` を画面で読めるようにする（`/help`、見出し単位のアンカー）。エラー表示の `E-...` コードから該当 FAQ へリンク。
- 各設定項目に「？」ツールチップ（`EDITABLE_CONFIG` に説明文を持たせて表示）。

### T28. データの書き出し・削除（P14）  依存: T6, T21

- 設定画面「データ管理」: 全データの書き出し（既存バックアップ形式）、認証情報だけの削除、全データ削除（`confirmed=true`＋確認文字入力）。ライセンス証明書の解除（T4 の deactivate）を先に案内する。
- インストーラのアンインストール時に「データも削除するか」を選ばせる（T12 / インストーラ作成時）。

### 番号なしの改善案（設計のみ。着手前に個別設計を PR 本文へ書く）

- F 勝ちパターン学習、C シーン編集、B 3ステップのホーム、E 通知、H タイトル・サムネ比較、I ネタ在庫、J 音声エンジン追加、K ローカル優先モード、L 他SNS書き出し、N PicoAgent 連携。

## 5. 未確認・リスク

- BOOTH 購入通知メールの実書式（v1 の自動取り込みの前提）。利用者から実物の提供待ち。
- Apps Script の Web アプリは呼び出し回数・実行時間の上限がある。販売規模が月数百本を超えたら Cloudflare Workers 等への移行を検討（その時点で外部依存の可否を利用者と判断）。
- MachineGuid は OS 再インストールで変わる。§1.3 のリセット申請で吸収する。
- 改名後の旧リポジトリURLはリダイレクトされるが、同名の新リポジトリを作るとリダイレクトが切れる。
