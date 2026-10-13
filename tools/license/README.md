# ライセンス発行（販売者用）

製品版のライセンスキーは、Google スプレッドシート＋Apps Script で自動発行する。アプリは購入キー（`NVF1.`）と端末固定証明書（`NVA1.`）を埋め込んだ公開鍵で検証する（`core/license_key.py`）。このフォルダは配布物に含めない。

## 全体の流れ

1. 購入者が BOOTH で購入する → 販売者の Gmail に購入通知が届く。
2. `importBoothOrders`（1時間ごと）が通知を読み、「注文」シートへ注文番号を追記する。
3. 購入者が Google フォームに注文番号・メールアドレス・お名前を送る。
4. `onFormSubmit` が注文番号を照合し、キーを発行して「発行済み」シートに記録、購入者へメールで送る。
5. アプリが購入キーと32桁の端末コードを Web アプリへ送信し、Standard 2台・Pro 3台の上限内で証明書を取得する。生端末 ID は送信・保存しない。
6. 証明書は30日間有効。アプリは期限の7日前から更新を試みる。返金時は「発行済み」の「失効」列に入力する。次回更新で失効が反映され、オフライン中は最長30日間の猶予がある。無期限の手動証明書には失効を反映できない。

## 初回設置

1. 既存の公開鍵・秘密鍵がある場合はそれを使い、生成し直さない。両方ともまだない新規発行環境だけ、1回生成する（公開鍵が存在するとツールは再生成を拒否する）:
   ```
   .\.venv\Scripts\python.exe tools/license/license_tool.py genkey
   ```
   秘密鍵は `~/.nvf_license/private_key.pem` に保存される。**必ずバックアップし、共有しない。**
   新規鍵を製品へ採用するときは `core/license_key.py` の公開鍵SHA-256固定値も同じPEMへ合わせて検証する。既存製品の鍵を変更すると発行済みキーはすべて無効になる。
2. スプレッドシートを作り、シートを4枚作る（1行目は見出し。列順を守る）:
   - `注文`: 注文番号 / 商品 / edition / packs / 受信日時 / メールID
   - `発行済み`: license_id / 注文番号 / メール / 購入者名 / edition / packs / 発行日 / 更新期限 / 失効 / メモ
   - `端末`: license_id / mid / 登録日時 / 最終更新日時 / 状態 / アプリ版
   - `リセット申請`: license_id / 申請日時 / 承認
   - 日時は UTC ISO 日時文字列、端末の状態は「有効」「解除済み」、承認は「自動」「手動確認待ち」「手動」。暦年の判定は日本時間。
3. 「拡張機能 > Apps Script」に `gas/Code.gs` を貼り付ける。
4. 「プロジェクトの設定 > スクリプトプロパティ」に `LICENSE_PRIVATE_KEY` を追加し、秘密鍵 PEM の全文を貼る。
5. Google フォームを作り、質問「注文番号」「メールアドレス」「お名前」を置いて回答先をこのスプレッドシートにする。
6. トリガーを追加する:
   - `importBoothOrders`: 時間主導型・1時間ごと
   - `onFormSubmit`: スプレッドシートから・フォーム送信時
7. 「デプロイ > 新しいデプロイ > ウェブアプリ」（実行ユーザー=自分、アクセス=全員）で公開し、`/exec` URL をアプリ設定 `LICENSE_API_URL` に登録する。`doGet ?lid=` は廃止し、証明書更新時に失効を確認する。コード変更後はデプロイ版も更新する。
8. `testIssueKey` を実行し、「キー署名確認: true」を確認する。キー・証明書は実行ログへ出さない。

既存 v1 の台帳・フォーム・発行トリガー・秘密鍵はそのまま使える。「端末」「リセット申請」を追加し、スクリプトと Web アプリのデプロイを更新する。発行済みの `NVF1.` キーは受け付けるが、v2 アプリでは証明書の取得が必要。台数・リース日数・年次リセット上限は `CONFIG.DEVICE_LIMITS` / `LEASE_DAYS` / `RESET_LIMIT` に集約している。

## API

JSON 本文を POST する。購入キー・証明書は URL のクエリへ含めない。

| action | 入力 | 成功 |
|---|---|---|
| activate | license_key, machine_code（小文字32hex）, app_version | activation, devices_registered, device_limit |
| renew | activation | activation, devices_registered, device_limit |
| deactivate | activation | ok: true |
| reset | license_key, order_number | ok: true |

エラーは `error` に `invalid`（入力・署名・未登録・注文不一致）、`revoked`、`inactive`（解除済み端末）、`limit`、`manual_review`、`server` を返す。HTTP ステータスだけで成功を判定しない。`limit` の `devices` は `[{mid: "末尾6桁", last_updated: "最終更新日時"}]`。購入キーと証明書の付与内容は同じで、上位版へ切り替える場合は新キーで登録する。期限切れでも署名と端末登録が有効なら更新・解除できる。

読み取り・台数判定・更新は発行トリガーと同じ `LockService` のロック内で実行し、`SpreadsheetApp.flush()` 後にロックを解放する。API の失敗ログは理由コードのみ。キー・証明書・秘密鍵をログへ書かない。

## 手動確認（専用のテスト台帳で行う）

本番の購入者台帳と切り離したシート・GAS を用意する。「発行済み」へテストキーの license_id・注文番号・メール・付与内容を記録する。スクリプトプロパティ `TEST_LICENSE_KEY` / `TEST_MACHINE_CODE`（32hex）/ `TEST_ORDER_NUMBER` を登録する。秘密のテスト値は終了後に削除する。

| 確認 | GAS エディタでの手順 | 期待結果 |
|---|---|---|
| 登録・再登録 | testActivate を2回 | ok、同じ端末は1行。TEST_ACTIVATION に証明書を保存 |
| 台数上限 | TEST_MACHINE_CODE を変えて上限＋1台まで testActivate | limit、有効台数が増えない |
| 更新 | 最初のコードへ戻して testActivate → testRenew | ok、最終更新日時と有効期限が延びる |
| 解除・再登録 | testDeactivate → testRenew → testActivate | ok → inactive → ok、解除によって枠が戻る |
| 失効 | 発行済みの失効列へ値を入れ testRenew / testActivate | revoked。確認後に失効列を戻す |
| 全端末リセット | testReset を同じ年に3回 | 1・2回目は ok、3回目は manual_review、販売者へ通知 |
| 注文照合 | TEST_ORDER_NUMBER を異なる値にして testReset | invalid、申請も端末も変更されない |
| 改変 | TEST_LICENSE_KEY の署名を1文字変えて testActivate | invalid、端末は増えない |

3回目以降の申請は、販売者が「リセット申請」を確認し、該当 license_id の有効端末をすべて「解除済み」に変更して承認列を「手動」にする。手動承認もその年の回数に含める。シートを直接編集する際は API と同時に編集しない。

ローカルのサービスモック・一時 RSA 鍵で検証する場合は `node tests/test_license_gas.mjs`。Python との双方向の実署名互換も検証する場合は `node tests/test_license_gas.mjs --python .venv/Scripts/python.exe`（macOS は `.venv/bin/python`）。一時テストデータは `temp/license-v2/` に集約し、検証後に削除する。実際の Apps Script の権限、シート更新、Web アプリのデプロイ、メール到達、同時リクエストはこのテストでは未確認。

## 要確認

- **BOOTH 購入通知メールの書式**: `CONFIG.BOOTH_MAIL_QUERY` / `ORDER_NUMBER_REGEX` / `PRODUCTS` は仮の値。実際の通知メールで件名・送信元・注文番号の書き方・商品名を確認して合わせる。解析できない通知があると販売者宛てに警告メールが届く。
- Gmail の送信上限（個人アカウントで1日100通程度）。

## 手動発行

注文と結びつかないキー（自分用・サポート対応など）は手元で発行できる:
```
.\.venv\Scripts\python.exe tools/license/license_tool.py issue --edition pro --buyer "名前" --update-months 0
```
アクティベーション API を使う場合は、出力された license_id と付与内容・送信先メールを「発行済み」に記録する。台帳未登録のキーは API が拒否する。

オフライン専用証明書は、販売者がスクリプトプロパティ `MANUAL_LICENSE_KEY` / `MANUAL_MACHINE_CODE` を設定し、GAS エディタから `issueOfflineActivation()` を実行する。台帳確認・台数上限を通して `exp` 空の証明書を発行し、台帳の登録メールへ送る。公開 API から無期限発行はできない。購入者は手動アクティベーション欄へ貼り付ける。実行後は手動用プロパティを削除する。
